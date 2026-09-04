from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from episignal_backend.db.types import PipelineRunStatus
from episignal_backend.operational_monitoring import (
    HealthStatus,
    PipelineHealthRecord,
    VolumeAnomaly,
    build_health_record,
    expected_runs_so_far,
    summarize_health,
)
from episignal_backend.schedule.documents import ChainOutcome, StageName, StageOutcome

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def run(
    *,
    started_at: datetime = NOW - timedelta(minutes=5),
    finished_at: datetime | None = NOW,
    status: PipelineRunStatus = PipelineRunStatus.SUCCEEDED,
    discovered: int | None = 10,
    duration_sec: float | None = 300,
    **overrides: object,
) -> PipelineHealthRecord:
    values: dict[str, object] = {
        "run_id": uuid4(),
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
        "discovered": discovered,
        "duration_sec": duration_sec,
    }
    values.update(overrides)
    return PipelineHealthRecord(**values)  # type: ignore[arg-type]


def test_build_health_record_maps_existing_stage_counts_without_changing_stages() -> None:
    outcome = ChainOutcome(
        outcomes=(
            StageOutcome(StageName.DISCOVER, True, {"discovered": 12}),
            StageOutcome(StageName.DEDUPE, True, {"primaries": 8, "duplicates": 4}),
            StageOutcome(
                StageName.CLASSIFY,
                True,
                {"requests": 10, "relevant": 3, "irrelevant": 7},
            ),
            StageOutcome(
                StageName.RETRIEVE,
                True,
                {
                    "examined": 3,
                    "retrieved": 2,
                    "duplicates": 1,
                    "redundant": 0,
                    "filtered": 0,
                    "failed": 0,
                },
            ),
            StageOutcome(StageName.EXTRACT, True, {"requests": 3, "extracted": 3}),
            StageOutcome(
                StageName.MATCH,
                True,
                {"seen": 3, "created": 1, "updated": 2, "attached": 2},
            ),
            StageOutcome(
                StageName.SUMMARIZE,
                True,
                {"summarized": 2, "failed": 0, "unavailable": 1},
            ),
        )
    )

    record = build_health_record(
        run_id=uuid4(),
        started_at=NOW - timedelta(minutes=5),
        finished_at=NOW,
        outcome=outcome,
    )

    assert record.status is PipelineRunStatus.SUCCEEDED
    assert record.duration_sec == 300
    assert record.discovered == 12
    assert record.dedup_primary == 8
    assert (record.deepseek_requested, record.deepseek_success, record.deepseek_relevant) == (
        10,
        10,
        3,
    )
    assert (record.retrieval_requested, record.retrieval_success) == (3, 3)
    assert (record.gemini_requested, record.gemini_success) == (3, 3)
    assert (record.grouping_requested, record.grouping_success) == (3, 2)
    assert (record.mistral_requested, record.mistral_success) == (3, 2)
    assert (record.new_events, record.updated_events) == (1, 2)
    assert record.duplicate_article_rate == pytest.approx(4 / 12)
    assert record.new_event_rate == pytest.approx(1 / 3)
    assert record.matched_existing_event_rate == pytest.approx(2 / 3)
    assert record.fatal_error_count == 0


def test_zero_relevant_signals_is_successful_telemetry() -> None:
    outcome = ChainOutcome(
        outcomes=(
            StageOutcome(StageName.CLASSIFY, True, {"requests": 4, "relevant": 0, "irrelevant": 4}),
        )
    )

    record = build_health_record(
        run_id=uuid4(), started_at=NOW - timedelta(minutes=1), finished_at=NOW, outcome=outcome
    )

    assert record.deepseek_success == 4
    assert record.deepseek_relevant == 0
    assert record.status is PipelineRunStatus.SUCCEEDED


def test_failed_stage_records_compact_error_category() -> None:
    outcome = ChainOutcome(
        outcomes=(StageOutcome(StageName.RETRIEVE, False, error="TimeoutError"),)
    )

    record = build_health_record(
        run_id=uuid4(), started_at=NOW - timedelta(minutes=1), finished_at=NOW, outcome=outcome
    )

    assert record.status is PipelineRunStatus.FAILED
    assert record.fatal_error_count == 1
    assert record.error_categories == {"TimeoutError": 1}


@pytest.mark.parametrize(
    ("coverage", "expected"),
    [
        (0.98, HealthStatus.HEALTHY),
        (0.9799, HealthStatus.WARNING),
        (0.95, HealthStatus.WARNING),
        (0.9499, HealthStatus.CRITICAL),
    ],
)
def test_coverage_thresholds(coverage: float, expected: HealthStatus) -> None:
    summary = summarize_health([run()], now=NOW, expected_runs=100, coverage_override=coverage)

    assert summary.coverage_status is expected


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (29.99, HealthStatus.HEALTHY),
        (30, HealthStatus.WARNING),
        (60, HealthStatus.WARNING),
        (60.01, HealthStatus.CRITICAL),
    ],
)
def test_freshness_thresholds(minutes: float, expected: HealthStatus) -> None:
    summary = summarize_health([run(finished_at=NOW - timedelta(minutes=minutes))], now=NOW)

    assert summary.freshness_status is expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (899.99, HealthStatus.HEALTHY),
        (900, HealthStatus.WARNING),
        (1800, HealthStatus.WARNING),
        (1800.01, HealthStatus.CRITICAL),
    ],
)
def test_p95_runtime_thresholds(seconds: float, expected: HealthStatus) -> None:
    summary = summarize_health([run(duration_sec=seconds)], now=NOW)

    assert summary.runtime_status is expected


def test_denominator_zero_is_neutral_not_zero_percent() -> None:
    summary = summarize_health([run(discovered=None)], now=NOW)

    assert summary.stage_success_rates["deepseek"].value is None
    assert summary.stage_success_rates["deepseek"].status is HealthStatus.NEUTRAL
    assert summary.success_rate == 1.0


def test_current_day_expected_runs_uses_bangkok_boundary() -> None:
    before_midnight_utc = datetime(2026, 9, 3, 16, 59, tzinfo=UTC)
    after_midnight_bangkok = datetime(2026, 9, 3, 17, 1, tzinfo=UTC)

    assert expected_runs_so_far(before_midnight_utc) == 96
    assert expected_runs_so_far(after_midnight_bangkok) == 1
    assert summarize_health([], now=after_midnight_bangkok).current_day_expected_runs_so_far == 1


def test_fatal_errors_and_stage_targets_contribute_to_health() -> None:
    summary = summarize_health(
        [
            run(
                status=PipelineRunStatus.FAILED,
                fatal_error_count=2,
                deepseek_requested=100,
                deepseek_success=98,
                retrieval_requested=100,
                retrieval_success=94,
            )
        ],
        now=NOW,
    )

    assert summary.fatal_error_status is HealthStatus.CRITICAL
    assert summary.stage_success_rates["deepseek"].status is HealthStatus.WARNING
    assert summary.stage_success_rates["retrieval"].status is HealthStatus.CRITICAL
    assert summary.status is HealthStatus.CRITICAL


def test_missed_runs_make_coverage_critical_but_zero_relevance_does_not() -> None:
    records = [run(discovered=0, deepseek_requested=0, deepseek_success=0, deepseek_relevant=0)]
    summary = summarize_health(records, now=NOW, expected_runs=96)

    assert summary.coverage_status is HealthStatus.CRITICAL
    assert summary.status is HealthStatus.CRITICAL
    assert summary.relevant == 0


def test_insufficient_seven_day_baseline_is_neutral_and_volume_not_critical() -> None:
    summary = summarize_health(
        [run(discovered=100, finished_at=NOW)]
        + [run(discovered=1, finished_at=NOW - timedelta(days=day)) for day in (1, 2)],
        now=NOW,
        expected_runs=1,
    )

    assert summary.volume_anomaly is VolumeAnomaly.INSUFFICIENT_DATA
    assert summary.baseline_status is HealthStatus.NEUTRAL
    assert summary.status is not HealthStatus.CRITICAL


def test_volume_anomaly_is_watch_only() -> None:
    records = [run(discovered=100, finished_at=NOW)] + [
        run(discovered=10, finished_at=NOW - timedelta(days=day)) for day in range(1, 8)
    ]
    summary = summarize_health(records, now=NOW, expected_runs=1)

    assert summary.volume_anomaly is VolumeAnomaly.HIGH
    assert summary.status is HealthStatus.HEALTHY


def test_unavailable_quality_and_latency_telemetry_is_null_with_reasons() -> None:
    outcome = ChainOutcome(outcomes=())
    record = build_health_record(
        run_id=uuid4(), started_at=NOW - timedelta(minutes=1), finished_at=NOW, outcome=outcome
    )

    assert record.unknown_disease_rate is None
    assert record.no_location_rate is None
    assert record.dashboard_response_ms is None
    assert "unknown_disease_rate" in record.unavailable_metrics
    assert "dashboard_response_ms" in record.unavailable_metrics
