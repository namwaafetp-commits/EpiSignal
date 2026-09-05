from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from episignal_backend.db.types import PipelineRunStatus, PipelineTrigger
from episignal_backend.operational_monitoring import (
    HealthStatus,
    PipelineHealthRecord,
    PipelineRunCoverageRecord,
    VolumeAnomaly,
    build_health_record,
    expected_runs_so_far,
    summarize_health,
)
from episignal_backend.schedule.documents import ChainOutcome, StageName, StageOutcome

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
BANGKOK = ZoneInfo("Asia/Bangkok")


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


def scheduled_run_at(
    hour: int,
    *,
    minute: int = 0,
    status: PipelineRunStatus = PipelineRunStatus.SUCCEEDED,
    now: datetime = datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK),
    **overrides: object,
) -> PipelineHealthRecord:
    started_at = datetime(2026, 9, 4, hour, minute, tzinfo=BANGKOK)
    values: dict[str, object] = {
        "started_at": started_at,
        "finished_at": started_at + timedelta(minutes=5),
        "status": status,
        "trigger": PipelineTrigger.SCHEDULED,
    }
    values.update(overrides)
    return run(**values)  # type: ignore[arg-type]


def pipeline_run_at(
    hour: int,
    *,
    minute: int = 0,
    status: PipelineRunStatus = PipelineRunStatus.SUCCEEDED,
) -> PipelineRunCoverageRecord:
    started_at = datetime(2026, 9, 4, hour, minute, tzinfo=BANGKOK)
    return PipelineRunCoverageRecord(
        run_id=uuid4(),
        started_at=started_at,
        finished_at=started_at + timedelta(minutes=5),
        status=status,
        trigger=PipelineTrigger.SCHEDULED,
    )


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


def test_gemini_health_uses_signal_count_when_retries_increase_provider_requests() -> None:
    outcome = ChainOutcome(
        outcomes=(
            StageOutcome(
                StageName.EXTRACT,
                True,
                {
                    "examined": 1,
                    "extracted": 1,
                    "rejected": 0,
                    "unavailable": 0,
                    "requests": 2,
                    "expanded_retries": 1,
                },
            ),
        )
    )

    record = build_health_record(
        run_id=uuid4(), started_at=NOW - timedelta(minutes=1), finished_at=NOW, outcome=outcome
    )
    summary = summarize_health([record], now=NOW)

    assert summary.stage_success_rates["gemini"].value == 1.0
    assert summary.stage_observability["gemini"] == {
        "examined": 1,
        "extracted": 1,
        "failed": 0,
        "unavailable": 0,
        "provider_requests": 2,
        "expanded_retries": 1,
    }


def test_gemini_health_reports_one_signal_and_one_provider_request_as_one_of_one() -> None:
    outcome = ChainOutcome(
        outcomes=(
            StageOutcome(
                StageName.EXTRACT,
                True,
                {"examined": 1, "extracted": 1, "requests": 1, "expanded_retries": 0},
            ),
        )
    )

    record = build_health_record(
        run_id=uuid4(), started_at=NOW - timedelta(minutes=1), finished_at=NOW, outcome=outcome
    )

    assert summarize_health([record], now=NOW).stage_success_rates["gemini"].value == 1.0


def test_gemini_health_counts_signal_level_partial_failure_not_provider_attempts() -> None:
    outcome = ChainOutcome(
        outcomes=(
            StageOutcome(
                StageName.EXTRACT,
                True,
                {
                    "examined": 2,
                    "extracted": 1,
                    "rejected": 0,
                    "unavailable": 1,
                    "requests": 3,
                    "expanded_retries": 1,
                },
            ),
        )
    )

    record = build_health_record(
        run_id=uuid4(), started_at=NOW - timedelta(minutes=1), finished_at=NOW, outcome=outcome
    )
    summary = summarize_health([record], now=NOW)

    assert summary.stage_success_rates["gemini"].value == 0.5
    assert summary.stage_observability["gemini"]["provider_requests"] == 3


def test_mistral_observability_keeps_skips_out_of_failure_denominator() -> None:
    outcome = ChainOutcome(
        outcomes=(
            StageOutcome(
                StageName.SUMMARIZE,
                True,
                {"examined": 4, "summarized": 1, "skipped": 1, "failed": 1, "unavailable": 1},
            ),
        )
    )

    record = build_health_record(
        run_id=uuid4(), started_at=NOW - timedelta(minutes=1), finished_at=NOW, outcome=outcome
    )
    summary = summarize_health([record], now=NOW)

    assert summary.stage_success_rates["mistral"].value == pytest.approx(1 / 3)
    assert summary.stage_observability["mistral"] == {
        "examined": 4,
        "summarized": 1,
        "skipped": 1,
        "failed": 1,
        "unavailable": 1,
    }


def test_retrieval_observability_preserves_terminal_states_and_failures() -> None:
    outcome = ChainOutcome(
        outcomes=(
            StageOutcome(
                StageName.RETRIEVE,
                True,
                {
                    "examined": 6,
                    "retrieved": 1,
                    "filtered": 1,
                    "duplicates": 1,
                    "redundant": 1,
                    "failed": 1,
                    "still_failing": 1,
                    "unclassified": 0,
                    "failure_http_429": 1,
                    "failure_domain:example.vn": 1,
                },
            ),
        )
    )

    record = build_health_record(
        run_id=uuid4(), started_at=NOW - timedelta(minutes=1), finished_at=NOW, outcome=outcome
    )
    summary = summarize_health([record], now=NOW)

    assert summary.stage_success_rates["retrieval"].value == pytest.approx(4 / 6)
    assert summary.stage_observability["retrieval"] == {
        "examined": 6,
        "retrieved": 1,
        "filtered": 1,
        "duplicates": 1,
        "redundant": 1,
        "failed": 1,
        "still_failing": 1,
        "unclassified": 0,
        "failure_categories": {"http_429": 1},
        "failure_domains": {"example.vn": 1},
    }


def test_build_health_record_exposes_stage_durations_and_failure_categories() -> None:
    outcome = ChainOutcome(
        outcomes=(
            StageOutcome(
                StageName.CLASSIFY,
                True,
                {"requests": 2, "relevant": 1, "irrelevant": 0, "failure_http_429": 1},
                duration_sec=1.25,
            ),
        )
    )

    record = build_health_record(
        run_id=uuid4(),
        started_at=NOW - timedelta(seconds=2),
        finished_at=NOW,
        outcome=outcome,
    )

    assert record.stage_durations_sec == {"classify": 1.25}
    assert record.error_categories == {"classify:http_429": 1}


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


def test_full_day_has_24_expected_runs() -> None:
    assert summarize_health([], now=NOW).expected_runs == 24


@pytest.mark.parametrize(
    ("local_time", "expected"),
    [
        (datetime(2026, 9, 4, 0, 0, tzinfo=BANGKOK), 1),
        (datetime(2026, 9, 4, 0, 30, tzinfo=BANGKOK), 1),
        (datetime(2026, 9, 4, 1, 30, tzinfo=BANGKOK), 2),
        (datetime(2026, 9, 4, 8, 10, tzinfo=BANGKOK), 9),
        (datetime(2026, 9, 4, 15, 0, tzinfo=BANGKOK), 16),
        (datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK), 16),
        (datetime(2026, 9, 4, 23, 59, tzinfo=BANGKOK), 24),
    ],
)
def test_expected_runs_so_far_uses_bangkok_hourly_slots(
    local_time: datetime, expected: int
) -> None:
    assert expected_runs_so_far(local_time) == expected


def test_current_day_expected_runs_uses_bangkok_boundary() -> None:
    before_midnight_utc = datetime(2026, 9, 3, 16, 59, tzinfo=UTC)
    after_midnight_bangkok = datetime(2026, 9, 3, 17, 1, tzinfo=UTC)

    assert expected_runs_so_far(before_midnight_utc) == 24
    assert expected_runs_so_far(after_midnight_bangkok) == 1
    assert summarize_health([], now=after_midnight_bangkok).current_day_expected_runs_so_far == 0


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
    records = [
        run(
            discovered=0,
            deepseek_requested=0,
            deepseek_success=0,
            deepseek_relevant=0,
            trigger=PipelineTrigger.SCHEDULED,
        )
    ]
    summary = summarize_health(records, now=NOW)

    assert summary.coverage_status is HealthStatus.CRITICAL
    assert summary.status is HealthStatus.CRITICAL
    assert summary.relevant == 0


def test_coverage_uses_hourly_denominator() -> None:
    now = datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK)
    one_run = summarize_health([scheduled_run_at(12, now=now)], now=now)
    full_day = summarize_health(
        [scheduled_run_at(hour, now=now) for hour in range(12, 16)], now=now
    )
    one_missed = summarize_health(
        [scheduled_run_at(hour, now=now) for hour in range(12, 15)], now=now
    )

    assert one_run.run_coverage == pytest.approx(1 / 4)
    assert full_day.run_coverage == 1.0
    assert one_missed.run_coverage == pytest.approx(3 / 4)
    assert one_missed.coverage_status is HealthStatus.CRITICAL


def test_current_day_coverage_counts_only_completed_scheduled_hourly_slots() -> None:
    now = datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK)
    summary = summarize_health([scheduled_run_at(hour, now=now) for hour in range(12, 16)], now=now)

    assert summary.current_day_expected_runs_so_far == 4
    assert summary.run_coverage == 1.0


def test_pipeline_run_without_health_row_covers_completed_scheduled_slot() -> None:
    now = datetime(2026, 9, 4, 17, 5, tzinfo=BANGKOK)
    coverage_runs = [pipeline_run_at(hour) for hour in range(12, 18)]

    summary = summarize_health([], now=now, coverage_runs=coverage_runs)

    assert summary.current_day_expected_runs_so_far == 6
    assert summary.run_coverage == 1.0


def test_five_completed_and_one_active_pipeline_run_cover_six_slots() -> None:
    now = datetime(2026, 9, 4, 17, 5, tzinfo=BANGKOK)
    active = PipelineRunCoverageRecord(
        run_id=uuid4(),
        started_at=datetime(2026, 9, 4, 17, 0, tzinfo=BANGKOK),
        finished_at=None,
        status=PipelineRunStatus.RUNNING,
        trigger=PipelineTrigger.SCHEDULED,
    )

    summary = summarize_health(
        [], now=now, coverage_runs=[pipeline_run_at(hour) for hour in range(12, 17)] + [active]
    )

    assert summary.run_coverage == 1.0


def test_failed_scheduled_pipeline_run_covers_its_slot_without_health_row() -> None:
    now = datetime(2026, 9, 4, 17, 5, tzinfo=BANGKOK)
    coverage_runs = [pipeline_run_at(hour) for hour in range(12, 17)]
    coverage_runs.append(pipeline_run_at(17, status=PipelineRunStatus.FAILED))

    summary = summarize_health([], now=now, coverage_runs=coverage_runs)

    assert summary.run_coverage == 1.0
    assert summary.completed_runs == 0
    assert summary.success_rate is None


def test_active_pipeline_run_is_coverage_only_when_explicitly_supplied() -> None:
    now = datetime(2026, 9, 4, 17, 5, tzinfo=BANGKOK)
    active = PipelineRunCoverageRecord(
        run_id=uuid4(),
        started_at=datetime(2026, 9, 4, 17, 0, tzinfo=BANGKOK),
        finished_at=None,
        status=PipelineRunStatus.RUNNING,
        trigger=PipelineTrigger.SCHEDULED,
    )

    summary = summarize_health([], now=now, coverage_runs=[active])

    assert summary.run_coverage == pytest.approx(1 / 6)
    assert summary.completed_runs == 0


def test_manual_pipeline_run_does_not_cover_scheduled_slot() -> None:
    now = datetime(2026, 9, 4, 17, 5, tzinfo=BANGKOK)
    manual = PipelineRunCoverageRecord(
        run_id=uuid4(),
        started_at=datetime(2026, 9, 4, 17, 0, tzinfo=BANGKOK),
        finished_at=now,
        status=PipelineRunStatus.SUCCEEDED,
        trigger=PipelineTrigger.MANUAL,
    )

    summary = summarize_health([], now=now, coverage_runs=[manual])

    assert summary.run_coverage == 0.0


def test_pipeline_run_occupancy_does_not_contaminate_health_denominators() -> None:
    now = datetime(2026, 9, 4, 17, 5, tzinfo=BANGKOK)
    health = scheduled_run_at(
        16,
        now=now,
        deepseek_requested=10,
        deepseek_success=10,
        retrieval_requested=10,
        retrieval_success=10,
    )
    coverage_runs = [
        pipeline_run_at(17, status=PipelineRunStatus.RUNNING),
        pipeline_run_at(15, status=PipelineRunStatus.FAILED),
    ]

    summary = summarize_health([health], now=now, coverage_runs=coverage_runs)

    assert summary.completed_runs == 1
    assert summary.success_rate == 1.0
    assert summary.stage_success_rates["deepseek"].value == 1.0
    assert summary.stage_success_rates["retrieval"].value == 1.0


def test_running_scheduled_run_covers_its_current_hourly_slot() -> None:
    now = datetime(2026, 9, 4, 17, 5, tzinfo=BANGKOK)
    completed = [scheduled_run_at(hour, now=now) for hour in range(12, 17)]
    active = run(
        started_at=datetime(2026, 9, 4, 17, 0, tzinfo=BANGKOK),
        finished_at=None,
        status=PipelineRunStatus.RUNNING,
        trigger=PipelineTrigger.SCHEDULED,
    )

    summary = summarize_health([*completed, active], now=now)

    assert summary.current_day_expected_runs_so_far == 6
    assert summary.run_coverage == 1.0


def test_five_completed_and_one_active_scheduled_slot_are_fully_covered() -> None:
    now = datetime(2026, 9, 4, 17, 5, tzinfo=BANGKOK)
    records = [scheduled_run_at(hour, now=now) for hour in range(12, 17)]
    records.append(
        run(
            started_at=datetime(2026, 9, 4, 17, 0, tzinfo=BANGKOK),
            finished_at=None,
            status=PipelineRunStatus.RUNNING,
            trigger=PipelineTrigger.SCHEDULED,
        )
    )

    summary = summarize_health(records, now=now)

    assert summary.run_coverage == 1.0
    assert summary.coverage_status is HealthStatus.HEALTHY


def test_manual_running_run_does_not_cover_a_scheduled_slot() -> None:
    now = datetime(2026, 9, 4, 17, 5, tzinfo=BANGKOK)
    records = [scheduled_run_at(hour, now=now) for hour in range(12, 17)]
    records.append(
        run(
            started_at=datetime(2026, 9, 4, 17, 0, tzinfo=BANGKOK),
            finished_at=None,
            status=PipelineRunStatus.RUNNING,
            trigger=PipelineTrigger.MANUAL,
        )
    )

    summary = summarize_health(records, now=now)

    assert summary.run_coverage == pytest.approx(5 / 6)


def test_active_scheduled_run_crossing_an_hour_covers_the_later_slot() -> None:
    now = datetime(2026, 9, 4, 17, 5, tzinfo=BANGKOK)
    records = [scheduled_run_at(hour, now=now) for hour in range(12, 16)]
    records.append(
        run(
            started_at=datetime(2026, 9, 4, 16, 30, tzinfo=BANGKOK),
            finished_at=None,
            status=PipelineRunStatus.RUNNING,
            trigger=PipelineTrigger.SCHEDULED,
        )
    )

    summary = summarize_health(records, now=now)

    assert summary.run_coverage == 1.0


def test_active_scheduled_run_crossing_midnight_covers_the_new_day_slot() -> None:
    now = datetime(2026, 9, 5, 0, 5, tzinfo=BANGKOK)
    active = run(
        started_at=datetime(2026, 9, 4, 23, 30, tzinfo=BANGKOK),
        finished_at=None,
        status=PipelineRunStatus.RUNNING,
        trigger=PipelineTrigger.SCHEDULED,
    )

    summary = summarize_health([active], now=now)

    assert summary.current_day_expected_runs_so_far == 1
    assert summary.run_coverage == 1.0


def test_stale_running_scheduled_run_does_not_cover_indefinitely() -> None:
    now = datetime(2026, 9, 4, 17, 30, tzinfo=BANGKOK)
    active = run(
        started_at=datetime(2026, 9, 4, 16, 0, tzinfo=BANGKOK),
        finished_at=None,
        status=PipelineRunStatus.RUNNING,
        trigger=PipelineTrigger.SCHEDULED,
    )

    summary = summarize_health([active], now=now)

    assert summary.run_coverage == 0.0


def test_running_records_do_not_enter_completed_success_or_stage_denominators() -> None:
    now = datetime(2026, 9, 4, 17, 5, tzinfo=BANGKOK)
    completed = scheduled_run_at(
        12,
        now=now,
        deepseek_requested=10,
        deepseek_success=10,
        retrieval_requested=10,
        retrieval_success=10,
    )
    active = run(
        started_at=datetime(2026, 9, 4, 17, 0, tzinfo=BANGKOK),
        finished_at=None,
        status=PipelineRunStatus.RUNNING,
        trigger=PipelineTrigger.SCHEDULED,
        deepseek_requested=100,
        deepseek_success=0,
        retrieval_requested=100,
        retrieval_success=0,
    )

    summary = summarize_health([completed, active], now=now)

    assert summary.completed_runs == 1
    assert summary.success_rate == 1.0
    assert summary.stage_success_rates["deepseek"].value == 1.0
    assert summary.stage_success_rates["retrieval"].value == 1.0


def test_old_quarter_hour_runs_in_one_hour_cover_one_slot() -> None:
    now = datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK)
    records = [scheduled_run_at(14, minute=minute, now=now) for minute in (0, 15, 30, 45)]

    summary = summarize_health(records, now=now)

    assert summary.run_coverage == pytest.approx(1 / 4)


def test_scheduled_runs_in_two_hours_cover_two_slots() -> None:
    now = datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK)

    summary = summarize_health(
        [scheduled_run_at(13, now=now), scheduled_run_at(14, now=now)], now=now
    )

    assert summary.run_coverage == pytest.approx(2 / 4)


def test_future_hour_is_not_counted_as_missed() -> None:
    now = datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK)
    summary = summarize_health(
        [scheduled_run_at(hour, now=now) for hour in range(12, 16)]
        + [scheduled_run_at(16, now=now)],
        now=now,
    )

    assert summary.run_coverage == 1.0


def test_duplicate_runs_cannot_push_current_day_coverage_above_100_percent() -> None:
    now = datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK)
    records = [scheduled_run_at(14, minute=minute, now=now) for minute in range(0, 60, 5)]

    summary = summarize_health(records, now=now)

    assert summary.run_coverage == pytest.approx(1 / 4)
    assert summary.run_coverage <= 1.0


def test_previous_day_records_do_not_cover_current_day_slots() -> None:
    now = datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK)
    previous_day = run(
        started_at=datetime(2026, 9, 3, 23, 0, tzinfo=BANGKOK),
        finished_at=datetime(2026, 9, 3, 23, 5, tzinfo=BANGKOK),
        trigger=PipelineTrigger.SCHEDULED,
    )

    summary = summarize_health([previous_day], now=now)

    assert summary.run_coverage == 0.0
    assert summary.success_rate == 1.0


def test_unknown_trigger_is_neutral_for_current_day_coverage() -> None:
    now = datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK)

    summary = summarize_health(
        [
            run(
                started_at=datetime(2026, 9, 4, 15, 0, tzinfo=BANGKOK),
                finished_at=datetime(2026, 9, 4, 15, 5, tzinfo=BANGKOK),
            )
        ],
        now=now,
    )

    assert summary.run_coverage is None
    assert summary.coverage_status is HealthStatus.NEUTRAL


def test_manual_run_does_not_cover_current_day_scheduled_slot() -> None:
    now = datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK)
    manual = run(
        started_at=datetime(2026, 9, 4, 15, 0, tzinfo=BANGKOK),
        finished_at=datetime(2026, 9, 4, 15, 5, tzinfo=BANGKOK),
        trigger=PipelineTrigger.MANUAL,
    )

    summary = summarize_health([manual], now=now)

    assert summary.run_coverage == 0.0


def test_monitoring_activation_starts_midday_on_transition_date() -> None:
    now = datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK)
    summary = summarize_health([], now=now)

    assert summary.current_day_expected_runs_so_far == 4
    assert summary.run_coverage == 0.0


def test_pre_activation_runs_do_not_affect_current_day_coverage() -> None:
    now = datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK)
    records = [scheduled_run_at(hour, now=now) for hour in (11, 12, 13, 14, 15)]

    summary = summarize_health(records, now=now)

    assert summary.current_day_expected_runs_so_far == 4
    assert summary.run_coverage == 1.0


def test_pre_activation_missing_slots_are_neutral() -> None:
    now = datetime(2026, 9, 4, 11, 59, tzinfo=BANGKOK)

    summary = summarize_health([], now=now)

    assert summary.current_day_expected_runs_so_far == 0
    assert summary.run_coverage is None
    assert summary.coverage_status is HealthStatus.NEUTRAL


def test_next_day_expected_slots_restart_at_bangkok_midnight() -> None:
    now = datetime(2026, 9, 5, 8, 10, tzinfo=BANGKOK)

    summary = summarize_health([], now=now)

    assert summary.current_day_expected_runs_so_far == 9


def test_pre_transition_day_has_neutral_scheduled_coverage() -> None:
    now = datetime(2026, 9, 3, 15, 17, tzinfo=BANGKOK)

    summary = summarize_health(
        [
            run(
                started_at=datetime(2026, 9, 3, 15, 0, tzinfo=BANGKOK),
                finished_at=datetime(2026, 9, 3, 15, 5, tzinfo=BANGKOK),
                trigger=PipelineTrigger.SCHEDULED,
            )
        ],
        now=now,
    )

    assert summary.run_coverage is None
    assert summary.coverage_status is HealthStatus.NEUTRAL
    assert summary.current_day_expected_runs_so_far == 0


def test_non_coverage_metrics_still_use_preceding_24_hours() -> None:
    now = datetime(2026, 9, 4, 15, 17, tzinfo=BANGKOK)
    current = scheduled_run_at(15, now=now, discovered=10, duration_sec=60)
    previous = run(
        started_at=datetime(2026, 9, 3, 23, 0, tzinfo=BANGKOK),
        finished_at=datetime(2026, 9, 3, 23, 5, tzinfo=BANGKOK),
        trigger=PipelineTrigger.MANUAL,
        status=PipelineRunStatus.FAILED,
        discovered=20,
        duration_sec=120,
        fatal_error_count=1,
    )

    summary = summarize_health([current, previous], now=now)

    assert summary.run_coverage == pytest.approx(1 / 4)
    assert summary.success_rate == 0.5
    assert summary.p95_runtime_sec == pytest.approx(117.0)
    assert summary.fatal_errors == 1


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
