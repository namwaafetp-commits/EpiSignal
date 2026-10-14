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
        recent_failures={"retrieval": ({"signal_id": "sig-1", "domain": "example.vn"},)},
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
    assert decoded["recent_failures"]["retrieval"][0]["domain"] == "example.vn"


def test_load_summary_reads_monitoring_once_under_read_only_transaction(monkeypatch):
    from unittest.mock import MagicMock, Mock

    from episignal_backend import monitoring_runner as runner

    session = Mock()
    scope = MagicMock()
    scope.__enter__.return_value = session
    monkeypatch.setattr(runner, "session_scope", Mock(return_value=scope))
    read_only = Mock()
    monkeypatch.setattr(runner, "enforce_read_only_transaction", read_only)
    repository = Mock()
    repository.recent_records.return_value = ()
    repository.recent_pipeline_runs.return_value = ()
    monkeypatch.setattr(runner, "SqlAlchemyPipelineHealthRepository", Mock(return_value=repository))
    evaluate = Mock(return_value="evaluated")
    monkeypatch.setattr(runner, "summarize_health", evaluate)
    now = datetime(2026, 9, 6, 1, tzinfo=UTC)
    assert runner.load_health_summary(now) == "evaluated"
    read_only.assert_called_once_with(session)
    repository.recent_records.assert_called_once_with(now)
    repository.recent_pipeline_runs.assert_called_once_with(now)
    evaluate.assert_called_once_with((), now=now, coverage_runs=())


def test_daily_command_evaluates_formats_and_sends_once(monkeypatch, tmp_path):
    from unittest.mock import Mock

    from episignal_backend import monitoring_notifications as notifications
    from episignal_backend import monitoring_runner as runner
    from episignal_backend.config import Settings
    from episignal_backend.operational_monitoring import summarize_health
    from episignal_backend.telegram import DeliveryResult

    config = Settings(
        _env_file=None,
        database_url="postgresql://test:test@localhost/test",
        telegram_bot_token="123:fake",
        telegram_chat_id="-123",
        telegram_state_path=tmp_path / "state.sqlite3",
    )
    value = summarize_health([], now=datetime(2026, 9, 6, tzinfo=UTC))
    load = Mock(return_value=value)
    formatter = Mock(return_value="daily text")
    send = Mock(return_value=DeliveryResult.DELIVERED)
    monkeypatch.setattr(runner, "load_health_summary", load)
    monkeypatch.setattr(runner, "get_settings", Mock(return_value=config))
    monkeypatch.setattr(notifications, "format_daily_report", formatter)
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    assert runner.main(["--daily-report"]) == 0
    load.assert_called_once()
    formatter.assert_called_once()
    send.assert_called_once_with("daily text", settings=config)


def test_monitor_failure_does_not_send_or_expose_exception(monkeypatch, caplog):
    from unittest.mock import Mock

    from episignal_backend import monitoring_runner as runner

    load = Mock(side_effect=RuntimeError("secret database URL"))
    notify = Mock()
    monkeypatch.setattr(runner, "load_health_summary", load)
    monkeypatch.setattr(runner, "notify_health", notify)
    assert runner.main(["--daily-report"]) == 1
    notify.assert_not_called()
    assert "monitoring_evaluation_failed" in caplog.text
    assert "secret database URL" not in caplog.text


def test_alert_delivery_failure_preserves_monitor_output_and_exit(monkeypatch, capsys):
    from unittest.mock import Mock

    from episignal_backend import monitoring_runner as runner
    from episignal_backend.operational_monitoring import summarize_health
    from episignal_backend.telegram import DeliveryResult

    value = summarize_health([], now=datetime(2026, 9, 6, tzinfo=UTC))
    monkeypatch.setattr(runner, "load_health_summary", Mock(return_value=value))
    monkeypatch.setattr(runner, "get_settings", Mock())
    monkeypatch.setattr(runner, "notify_health", Mock(return_value=DeliveryResult.FAILED))
    assert runner.main(["--notify"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == value.status.value


def test_default_command_remains_read_only_without_notifications(monkeypatch, capsys):
    from unittest.mock import Mock

    from episignal_backend import monitoring_runner as runner
    from episignal_backend.operational_monitoring import summarize_health

    monkeypatch.setattr(
        runner,
        "load_health_summary",
        Mock(return_value=summarize_health([], now=datetime(2026, 9, 6, tzinfo=UTC))),
    )
    notify = Mock()
    config = Mock()
    monkeypatch.setattr(runner, "notify_health", notify)
    monkeypatch.setattr(runner, "get_settings", config)
    assert runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "critical"
    notify.assert_not_called()
    config.assert_not_called()


def test_smoke_test_sends_static_text_without_monitoring_or_state(monkeypatch):
    from unittest.mock import Mock

    from episignal_backend import monitoring_runner as runner
    from episignal_backend.telegram import DeliveryResult

    load = Mock()
    notify = Mock()
    send = Mock(return_value=DeliveryResult.DELIVERED)
    monkeypatch.setattr(runner, "load_health_summary", load)
    monkeypatch.setattr(runner, "notify_health", notify)
    monkeypatch.setattr(runner, "send_telegram_message", send)
    monkeypatch.setattr(runner, "get_settings", Mock())
    assert runner.main(["--telegram-smoke-test"]) == 0
    send.assert_called_once()
    assert "notification-only smoke test" in send.call_args.args[0]
    load.assert_not_called()
    notify.assert_not_called()


def test_daily_delivery_failure_returns_nonzero(monkeypatch):
    from unittest.mock import Mock

    from episignal_backend import monitoring_runner as runner
    from episignal_backend.operational_monitoring import summarize_health
    from episignal_backend.telegram import DeliveryResult

    monkeypatch.setattr(
        runner,
        "load_health_summary",
        Mock(return_value=summarize_health([], now=datetime(2026, 9, 6, tzinfo=UTC))),
    )
    monkeypatch.setattr(runner, "get_settings", Mock())
    monkeypatch.setattr(runner, "notify_health", Mock(return_value=DeliveryResult.FAILED))
    assert runner.main(["--daily-report"]) == 1


def test_notification_configuration_exception_does_not_fail_monitor(monkeypatch, caplog):
    from unittest.mock import Mock

    from episignal_backend import monitoring_runner as runner
    from episignal_backend.operational_monitoring import summarize_health

    monkeypatch.setattr(
        runner,
        "load_health_summary",
        Mock(return_value=summarize_health([], now=datetime(2026, 9, 6, tzinfo=UTC))),
    )
    monkeypatch.setattr(
        runner, "get_settings", Mock(side_effect=ValueError("secret configuration"))
    )
    assert runner.main(["--notify"]) == 0
    assert "notification_failed reason=configuration" in caplog.text
    assert "secret configuration" not in caplog.text
