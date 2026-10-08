from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from episignal_backend.db.types import PipelineRunStatus, PipelineTrigger
from episignal_backend.monitoring_messages import (
    abnormal_fingerprint,
    format_abnormal_alert,
    format_daily_report,
    format_recovery,
)
from episignal_backend.operational_monitoring import (
    HealthMetric,
    HealthStatus,
    PipelineHealthRecord,
    summarize_health,
)

NOW = datetime(2026, 9, 6, 1, 5, tzinfo=UTC)


def _healthy_summary():
    record = PipelineHealthRecord(
        run_id=uuid4(),
        started_at=NOW - timedelta(minutes=5),
        finished_at=NOW,
        status=PipelineRunStatus.SUCCEEDED,
        trigger=PipelineTrigger.SCHEDULED,
        duration_sec=300,
        discovered=12,
        deepseek_requested=10,
        deepseek_success=10,
        deepseek_relevant=0,
        retrieval_requested=10,
        retrieval_success=10,
        gemini_requested=10,
        gemini_success=10,
        grouping_requested=10,
        grouping_success=10,
        mistral_requested=10,
        mistral_success=10,
        new_events=1,
        updated_events=2,
        summarized_events=3,
        fatal_error_count=0,
    )
    return summarize_health([record], now=NOW, expected_runs=1, coverage_override=1.0)


def test_daily_report_renders_a_healthy_snapshot_from_the_evaluator() -> None:
    report = format_daily_report(_healthy_summary(), now=NOW)

    assert (
        report
        == """🟢 EpiSignal Daily Health
6 Sep 2026 (ICT)

Pipeline (coverage: current ICT day; output and runs: trailing 24h)
✓ Coverage: 100% (9 scheduled slots due today)
✓ Run success: 1/1 (100%)
✓ Freshness: 0m
✓ p95 runtime: 5m
✓ Fatal errors: 0
✓ Last completed run: 6 Sep 2026 08:05 ICT

Stages
✓ DeepSeek: 100% (healthy ≥99%)
✓ Retrieval: 100% (healthy ≥95%)
✓ Gemini: 100% (healthy ≥98%)
✓ Grouping: 100% (healthy ≥99%)
✓ Mistral: 100% (healthy ≥98%)

24h Output
Discovered: 12
Relevant: 0
New events: 1
Updated events: 2
Summarized events: 3

Recent failures
None

Overall: HEALTHY"""
    )


def test_abnormal_alert_lists_every_abnormal_pipeline_metric_and_all_stages() -> None:
    record = PipelineHealthRecord(
        run_id=uuid4(),
        started_at=NOW - timedelta(minutes=46),
        finished_at=NOW - timedelta(minutes=31),
        status=PipelineRunStatus.SUCCEEDED,
        trigger=PipelineTrigger.SCHEDULED,
        duration_sec=900,
        deepseek_requested=100,
        deepseek_success=98,
        retrieval_requested=100,
        retrieval_success=100,
        gemini_requested=100,
        gemini_success=100,
        grouping_requested=100,
        grouping_success=100,
        mistral_requested=100,
        mistral_success=100,
        fatal_error_count=1,
    )
    summary = summarize_health([record], now=NOW, expected_runs=1, coverage_override=1.0)

    alert = format_abnormal_alert(summary, now=NOW)

    assert alert.startswith("🟡 EpiSignal WARNING\n6 Sep 2026 08:05 ICT")
    assert "🟡 Freshness: 31m (healthy <30m)" in alert
    assert "🟡 p95 runtime: 15m (healthy <15m)" in alert
    assert "🟡 Fatal errors: 1 (healthy 0)" in alert
    assert "🟡 DeepSeek: 98% (healthy ≥99%)" in alert
    for stage in ("Retrieval", "Gemini", "Grouping", "Mistral"):
        assert f"✓ {stage}: 100%" in alert


def test_recovery_reports_the_previous_evaluator_status() -> None:
    recovery = format_recovery(_healthy_summary(), previous_status=HealthStatus.CRITICAL, now=NOW)

    assert (
        recovery
        == """🟢 EpiSignal RECOVERED
Previous status: CRITICAL
Current status: HEALTHY

Coverage: 100% (9 scheduled slots due today)
Run success: 1/1 (100%)
Freshness: 0m

Recovered: 6 Sep 2026 08:05 ICT"""
    )


def test_abnormal_fingerprint_uses_statuses_not_metric_values_and_changes_with_identity() -> None:
    record = PipelineHealthRecord(
        run_id=uuid4(),
        started_at=NOW - timedelta(minutes=6),
        finished_at=NOW - timedelta(minutes=1),
        status=PipelineRunStatus.SUCCEEDED,
        trigger=PipelineTrigger.SCHEDULED,
        deepseek_requested=100,
        deepseek_success=98,
    )
    summary = summarize_health([record], now=NOW, expected_runs=1, coverage_override=1.0)
    changed_value = replace(
        summary,
        stage_success_rates={
            **summary.stage_success_rates,
            "deepseek": HealthMetric(0.97, HealthStatus.WARNING),
        },
    )
    changed_identity = replace(changed_value, freshness_status=HealthStatus.WARNING)

    assert abnormal_fingerprint(summary) == abnormal_fingerprint(changed_value)
    assert abnormal_fingerprint(summary) == "warning|stage:deepseek:warning"
    assert (
        abnormal_fingerprint(changed_identity) == "warning|freshness:warning|stage:deepseek:warning"
    )


def test_daily_report_bounds_and_sanitizes_recent_retrieval_and_mistral_failures() -> None:
    retrieval_failures = tuple(
        {
            "domain": "example.org",
            "category": "http_403",
            "http_status": 403,
            "exception_class": "SecretError",
            "message": "token=should-not-appear",
            "url": "https://example.org/?api_key=should-not-appear",
        }
        for _ in range(6)
    )
    mistral_failures = tuple(
        {
            "category": "provider_unavailable",
            "provider_status_class": "5xx",
            "prompt": "should-not-appear",
            "response": "should-not-appear",
        }
        for _ in range(6)
    )
    summary = replace(
        _healthy_summary(),
        recent_failures={"retrieval": retrieval_failures, "mistral": mistral_failures},
    )

    report = format_daily_report(summary, now=NOW)
    failure_lines = [line for line in report.splitlines() if line.startswith("- ")]

    assert len(failure_lines) == 8
    assert failure_lines[0] == "- Retrieval: example.org — HTTP 403"
    assert failure_lines[-1] == "- Mistral: provider unavailable (HTTP 5xx)"
    assert "should-not-appear" not in report


def test_daily_report_keeps_a_zero_denominator_stage_as_na() -> None:
    healthy = _healthy_summary()
    summary = replace(
        healthy,
        stage_success_rates={
            **healthy.stage_success_rates,
            "retrieval": HealthMetric(None, HealthStatus.NEUTRAL),
        },
    )

    assert "✓ Retrieval: N/A (healthy ≥95%)" in format_daily_report(summary, now=NOW)


def test_daily_report_uses_the_evaluator_critical_status() -> None:
    record = PipelineHealthRecord(
        run_id=uuid4(),
        started_at=NOW - timedelta(minutes=62),
        finished_at=NOW - timedelta(minutes=61),
        status=PipelineRunStatus.FAILED,
        trigger=PipelineTrigger.SCHEDULED,
        duration_sec=1801,
        retrieval_requested=100,
        retrieval_success=94,
        fatal_error_count=2,
    )
    summary = summarize_health([record], now=NOW, expected_runs=1, coverage_override=1.0)

    report = format_daily_report(summary, now=NOW)

    assert report.startswith("🔴 EpiSignal Daily Health")
    assert "Overall: CRITICAL" in report


def test_daily_report_handles_missing_stage_metrics_as_na() -> None:
    summary = replace(_healthy_summary(), stage_success_rates={})

    report = format_daily_report(summary, now=NOW)

    assert "✓ DeepSeek: N/A (healthy ≥99%)" in report
    assert "✓ Retrieval: N/A (healthy ≥95%)" in report
    assert "✓ Gemini: N/A (healthy ≥98%)" in report
    assert "✓ Grouping: N/A (healthy ≥99%)" in report
    assert "✓ Mistral: N/A (healthy ≥98%)" in report


def test_daily_report_does_not_use_trailing_completed_runs_as_coverage_numerator() -> None:
    summary = replace(
        _healthy_summary(),
        completed_runs=24,
        current_day_expected_runs_so_far=8,
        run_coverage=1.0,
    )

    report = format_daily_report(summary, now=NOW)

    assert "Coverage: 100% (8 scheduled slots due today)" in report
    assert "24/8" not in report


def test_daily_report_keeps_fractional_percentage_precision() -> None:
    summary = replace(_healthy_summary(), run_coverage=0.989, coverage_status=HealthStatus.WARNING)

    assert "🟡 Coverage: 98.9%" in format_daily_report(summary, now=NOW)


def test_daily_warning_message_uses_evaluator_status_and_warned_metric() -> None:
    summary = replace(
        _healthy_summary(),
        status=HealthStatus.WARNING,
        freshness_minutes=45,
        freshness_status=HealthStatus.WARNING,
    )
    report = format_daily_report(summary, now=NOW)
    assert report.startswith("🟡 EpiSignal Daily Health\n6 Sep 2026 (ICT)")
    assert "🟡 Freshness: 45m" in report
    assert report.endswith("Overall: WARNING")
    assert "Relevant: 0" in report
