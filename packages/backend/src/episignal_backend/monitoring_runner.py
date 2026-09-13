"""Read-only command for the deterministic pipeline health summary."""

import argparse
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime

from episignal_backend.config import get_settings
from episignal_backend.db.session import enforce_read_only_transaction, session_scope
from episignal_backend.monitoring_notifications import notify_health
from episignal_backend.monitoring_repository import SqlAlchemyPipelineHealthRepository
from episignal_backend.operational_monitoring import HealthMetric, HealthSummary, summarize_health
from episignal_backend.telegram import DeliveryResult, send_telegram_message

logger = logging.getLogger(__name__)


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


def load_health_summary(now: datetime) -> HealthSummary:
    """Read the normal monitoring evidence and evaluate it exactly once."""
    with session_scope() as session:
        enforce_read_only_transaction(session)
        repository = SqlAlchemyPipelineHealthRepository(session)
        records = repository.recent_records(now)
        coverage_runs = repository.recent_pipeline_runs(now)
    return summarize_health(records, now=now, coverage_runs=coverage_runs)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--notify", action="store_true", help="Send abnormal transitions/recovery")
    mode.add_argument("--daily-report", action="store_true", help="Send once per Bangkok date")
    mode.add_argument(
        "--telegram-smoke-test", action="store_true", help="Send static text; no database access"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if args.telegram_smoke_test:
        try:
            smoke_result = send_telegram_message(
                "EpiSignal notification-only smoke test. No surveillance run was started.",
                settings=get_settings(),
            )
            logger.info("telegram_smoke_test result=%s", smoke_result.value)
            return 1 if smoke_result is DeliveryResult.FAILED else 0
        except Exception:
            logger.warning("telegram_smoke_test_failed reason=configuration")
            return 1
    now = datetime.now(UTC)
    try:
        summary = load_health_summary(now)
    except Exception:
        logger.warning("monitoring_evaluation_failed")
        return 1
    if not args.daily_report:
        print(json.dumps(health_summary_to_dict(summary), sort_keys=True))
    if args.notify or args.daily_report:
        try:
            result = notify_health(
                summary, now=now, settings=get_settings(), daily=args.daily_report
            )
        except Exception:
            logger.warning("notification_failed reason=configuration")
            result = DeliveryResult.FAILED
        # Alert delivery never changes the normal monitoring exit status.
        if args.daily_report and result is DeliveryResult.FAILED:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
