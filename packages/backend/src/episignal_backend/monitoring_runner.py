"""Read-only command for the deterministic pipeline health summary."""

import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime

from episignal_backend.db.session import enforce_read_only_transaction, session_scope
from episignal_backend.monitoring_repository import SqlAlchemyPipelineHealthRepository
from episignal_backend.operational_monitoring import HealthMetric, HealthSummary, summarize_health


def health_summary_to_dict(summary: HealthSummary) -> dict[str, object]:
    """Return a JSON-safe structured representation for operators and scripts."""
    result = asdict(summary)
    result["status"] = summary.status.value
    result["latest_run"] = summary.latest_run.isoformat() if summary.latest_run else None
    result["volume_anomaly"] = summary.volume_anomaly.value
    result["stage_success_rates"] = _metrics_to_dict(summary.stage_success_rates)
    result["quality_watch"] = _metrics_to_dict(summary.quality_watch)
    return result


def _metrics_to_dict(metrics: Mapping[str, HealthMetric]) -> dict[str, object]:
    return {
        name: {"value": metric.value, "status": metric.status.value}
        for name, metric in metrics.items()
    }


def main() -> int:
    now = datetime.now(UTC)
    with session_scope() as session:
        enforce_read_only_transaction(session)
        repository = SqlAlchemyPipelineHealthRepository(session)
        records = repository.recent_records(now)
        coverage_runs = repository.recent_pipeline_runs(now)
    summary = summarize_health(records, now=now, coverage_runs=coverage_runs)
    print(json.dumps(health_summary_to_dict(summary), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
