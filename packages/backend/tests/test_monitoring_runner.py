import json
from datetime import UTC, datetime

from episignal_backend.monitoring_runner import health_summary_to_dict
from episignal_backend.operational_monitoring import (
    HealthMetric,
    HealthStatus,
    HealthSummary,
    VolumeAnomaly,
)


def test_health_summary_serializes_to_structured_json() -> None:
    summary = HealthSummary(
        status=HealthStatus.HEALTHY,
        expected_runs=24,
        current_day_expected_runs_so_far=4,
        completed_runs=24,
        run_coverage=1.0,
        coverage_status=HealthStatus.HEALTHY,
        successful_runs=24,
        success_rate=1.0,
        success_status=HealthStatus.HEALTHY,
        latest_run=datetime(2026, 9, 4, 5, 0, tzinfo=UTC),
        freshness_minutes=1.0,
        freshness_status=HealthStatus.HEALTHY,
        p95_runtime_sec=30.0,
        runtime_status=HealthStatus.HEALTHY,
        fatal_errors=0,
        fatal_error_status=HealthStatus.HEALTHY,
        stage_success_rates={"deepseek": HealthMetric(1.0, HealthStatus.HEALTHY)},
        discovered=10,
        relevant=2,
        new_events=1,
        updated_events=1,
        summarized_events=2,
        baseline_discovered_per_day=None,
        baseline_status=HealthStatus.NEUTRAL,
        volume_anomaly=VolumeAnomaly.INSUFFICIENT_DATA,
        quality_watch={"unknown_disease_rate": HealthMetric(None, HealthStatus.NEUTRAL)},
        unavailable_metrics={"endpoint_latency_ms": "not instrumented"},
        stage_observability={"gemini": {"examined": 1, "extracted": 1}},
    )

    decoded = json.loads(json.dumps(health_summary_to_dict(summary)))

    assert decoded["status"] == "healthy"
    assert decoded["latest_run"] == "2026-09-04T05:00:00+00:00"
    assert decoded["stage_success_rates"]["deepseek"] == {
        "value": 1.0,
        "status": "healthy",
    }
    assert decoded["quality_watch"]["unknown_disease_rate"]["value"] is None
    assert decoded["stage_observability"]["gemini"] == {"examined": 1, "extracted": 1}
