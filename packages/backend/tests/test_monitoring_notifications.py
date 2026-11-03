from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from episignal_backend.config import Settings
from episignal_backend.operational_monitoring import HealthMetric, HealthStatus, summarize_health
from episignal_backend.telegram import DeliveryResult

NOW = datetime(2026, 9, 6, 1, tzinfo=UTC)


def summary(status=HealthStatus.HEALTHY, condition="retrieval", value=0.96):
    base = replace(
        summarize_health([], now=NOW, coverage_override=1),
        status=status,
        freshness_minutes=5,
        freshness_status=HealthStatus.HEALTHY,
    )
    if status in (HealthStatus.WARNING, HealthStatus.CRITICAL):
        if condition == "freshness":
            return replace(base, freshness_minutes=45, freshness_status=status)
        return replace(
            base,
            stage_success_rates={
                **base.stage_success_rates,
                condition: HealthMetric(value, status),
            },
        )
    return base


@pytest.fixture
def config(tmp_path):
    return Settings(
        _env_file=None,
        database_url="postgresql://test:test@localhost/test",
        telegram_bot_token="123:secret",
        telegram_chat_id="-10042",
        telegram_state_path=tmp_path / "state.sqlite3",
    )


@pytest.mark.parametrize(
    "statuses,expected",
    [
        (["healthy", "healthy"], []),
        (["healthy", "warning"], ["WARNING"]),
        (["healthy", "critical"], ["CRITICAL"]),
        (["warning", "warning"], ["WARNING"]),
        (["warning", "critical"], ["WARNING", "CRITICAL"]),
        (["critical", "critical"], ["CRITICAL"]),
        (["critical", "healthy", "healthy"], ["CRITICAL", "RECOVERED"]),
        (["warning", "healthy", "healthy"], ["WARNING", "RECOVERED"]),
        (["critical", "warning"], ["CRITICAL", "WARNING"]),
    ],
)
def test_transition_sequence(config, monkeypatch, statuses, expected):
    from episignal_backend import monitoring_notifications as notifications

    send = Mock(return_value=DeliveryResult.DELIVERED)
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    for index, status in enumerate(statuses):
        notifications.notify_health(
            summary(HealthStatus(status)), now=NOW + timedelta(minutes=index), settings=config
        )
    headers = [call.args[0].splitlines()[0] for call in send.call_args_list]
    assert len(headers) == len(expected)
    for header, word in zip(headers, expected, strict=True):
        assert word in header


def test_changed_condition_alerts_but_small_numeric_change_does_not(config, monkeypatch):
    from episignal_backend import monitoring_notifications as notifications

    send = Mock(return_value=DeliveryResult.DELIVERED)
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    for index, (condition, value) in enumerate(
        [("gemini", 0.96), ("gemini", 0.961), ("freshness", 45)]
    ):
        notifications.notify_health(
            summary(HealthStatus.WARNING, condition, value),
            now=NOW + timedelta(minutes=index),
            settings=config,
        )
    assert send.call_count == 2


def test_restart_does_not_duplicate_active_incident(config, monkeypatch):
    from episignal_backend import monitoring_notifications as notifications

    send = Mock(return_value=DeliveryResult.DELIVERED)
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    notifications.notify_health(summary(HealthStatus.WARNING), now=NOW, settings=config)
    # No process memory is retained: a fresh settings/store invocation reopens the file.
    notifications.notify_health(
        summary(HealthStatus.WARNING), now=NOW + timedelta(minutes=1), settings=config.model_copy()
    )
    send.assert_called_once()


def test_failed_alert_retried_on_next_evaluation(config, monkeypatch, caplog):
    from episignal_backend import monitoring_notifications as notifications

    send = Mock(side_effect=[DeliveryResult.FAILED, DeliveryResult.DELIVERED])
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    for index in range(3):
        notifications.notify_health(
            summary(HealthStatus.CRITICAL), now=NOW + timedelta(minutes=index), settings=config
        )
    assert send.call_count == 2
    assert "alert_failed" in caplog.text


def test_failed_recovery_retried_then_cleared(config, monkeypatch):
    from episignal_backend import monitoring_notifications as notifications

    send = Mock(
        side_effect=[DeliveryResult.DELIVERED, DeliveryResult.FAILED, DeliveryResult.DELIVERED]
    )
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    for index, status in enumerate(["warning", "healthy", "healthy", "healthy"]):
        notifications.notify_health(
            summary(HealthStatus(status)), now=NOW + timedelta(minutes=index), settings=config
        )
    assert send.call_count == 3
    assert "RECOVERED" in send.call_args.args[0]


def test_stale_snapshot_cannot_recover_newer_incident(config, monkeypatch):
    from episignal_backend import monitoring_notifications as notifications

    send = Mock(return_value=DeliveryResult.DELIVERED)
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    notifications.notify_health(summary(HealthStatus.CRITICAL), now=NOW, settings=config)
    notifications.notify_health(summary(), now=NOW - timedelta(minutes=1), settings=config)
    send.assert_called_once()


def test_daily_once_per_bangkok_date_independent_of_alert_state(config, monkeypatch):
    from episignal_backend import monitoring_notifications as notifications

    send = Mock(return_value=DeliveryResult.DELIVERED)
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    notifications.notify_health(summary(HealthStatus.WARNING), now=NOW, settings=config)
    for instant in [NOW, NOW + timedelta(hours=15), NOW + timedelta(hours=16)]:
        notifications.notify_health(summary(), now=instant, settings=config, daily=True)
    notifications.notify_health(summary(), now=NOW + timedelta(hours=17), settings=config)
    assert send.call_count == 4  # warning, 2 Bangkok dates, recovery


def test_failed_daily_is_not_marked_delivered(config, monkeypatch):
    from episignal_backend import monitoring_notifications as notifications

    send = Mock(side_effect=[DeliveryResult.FAILED, DeliveryResult.DELIVERED])
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    for index in range(3):
        notifications.notify_health(
            summary(), now=NOW + timedelta(minutes=index), settings=config, daily=True
        )
    assert send.call_count == 2


@pytest.mark.parametrize(
    "missing", ["telegram_bot_token", "telegram_chat_id", "telegram_state_path"]
)
def test_missing_configuration_nonfatal_no_send(config, monkeypatch, missing):
    from episignal_backend import monitoring_notifications as notifications

    send = Mock()
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    values = config.model_dump()
    values[missing] = None if missing == "telegram_state_path" else ""
    result = notifications.notify_health(
        summary(HealthStatus.CRITICAL), now=NOW, settings=Settings(**values)
    )
    assert result is DeliveryResult.DISABLED
    send.assert_not_called()


def test_corrupt_state_fails_closed_without_sensitive_logs(config, monkeypatch, caplog):
    from episignal_backend import monitoring_notifications as notifications

    config.telegram_state_path.write_text("secret invalid state")
    send = Mock()
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    assert (
        notifications.notify_health(summary(HealthStatus.CRITICAL), now=NOW, settings=config)
        is DeliveryResult.FAILED
    )
    send.assert_not_called()
    assert "secret" not in caplog.text


def test_neutral_does_not_claim_recovery(config, monkeypatch):
    from episignal_backend import monitoring_notifications as notifications

    send = Mock(return_value=DeliveryResult.DELIVERED)
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    notifications.notify_health(summary(HealthStatus.WARNING), now=NOW, settings=config)
    notifications.notify_health(
        summary(HealthStatus.NEUTRAL), now=NOW + timedelta(minutes=1), settings=config
    )
    send.assert_called_once()


def test_real_process_restart_preserves_alert_checkpoint(config):
    import subprocess
    import sys

    script = """
import sys
from datetime import UTC, datetime
from episignal_backend.config import Settings
from episignal_backend.operational_monitoring import summarize_health
from episignal_backend import monitoring_notifications as notifications
from episignal_backend.telegram import DeliveryResult
settings = Settings(_env_file=None, database_url="postgresql://test:test@localhost/test",
    telegram_bot_token="123:fake", telegram_chat_id="-123", telegram_state_path=sys.argv[1])
def send(text, *, settings):
    print("SENT")
    return DeliveryResult.DELIVERED
notifications.send_telegram_message = send
now = datetime(2026, 9, 6, 1, tzinfo=UTC)
notifications.notify_health(summarize_health([], now=now), now=now, settings=settings)
"""
    outputs = [
        subprocess.run(
            [sys.executable, "-c", script, str(config.telegram_state_path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        for _ in range(2)
    ]
    assert outputs == ["SENT\n", ""]


@pytest.mark.parametrize("status", [HealthStatus.WARNING, HealthStatus.CRITICAL])
def test_recurrence_after_failed_recovery_is_a_new_incident(config, monkeypatch, status):
    from episignal_backend import monitoring_notifications as notifications

    send = Mock(
        side_effect=[
            DeliveryResult.DELIVERED,
            DeliveryResult.FAILED,
            DeliveryResult.FAILED,
            DeliveryResult.DELIVERED,
        ]
    )
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    # Every call reopens SQLite, including after failed recovery and failed recurrence.
    for index, current in enumerate([status, HealthStatus.HEALTHY, status, status, status]):
        notifications.notify_health(
            summary(current), now=NOW + timedelta(minutes=index), settings=config.model_copy()
        )
    assert send.call_count == 4
    assert "RECOVERED" in send.call_args_list[1].args[0]
    assert status.value.upper() in send.call_args_list[2].args[0].splitlines()[0]


def test_failed_new_condition_does_not_hide_return_to_previous_condition(config, monkeypatch):
    from episignal_backend import monitoring_notifications as notifications

    send = Mock(
        side_effect=[DeliveryResult.DELIVERED, DeliveryResult.FAILED, DeliveryResult.DELIVERED]
    )
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    for index, condition in enumerate(["gemini", "freshness", "gemini", "gemini"]):
        notifications.notify_health(
            summary(HealthStatus.WARNING, condition),
            now=NOW + timedelta(minutes=index),
            settings=config,
        )
    assert send.call_count == 3


@pytest.mark.parametrize("outer_daily", [False, True])
def test_daily_alert_lock_contention_leaves_loser_eligible_for_retry(
    config, monkeypatch, caplog, outer_daily
):
    from episignal_backend import monitoring_notifications as notifications

    snapshot = summary(HealthStatus.CRITICAL)
    messages = []
    blocked_results = []

    def send(text, *, settings):
        messages.append(text)
        if len(messages) == 1:
            # The first real notification transaction is still holding the file lock.
            blocked_results.append(
                notifications.notify_health(
                    snapshot, now=NOW, settings=config, daily=not outer_daily
                )
            )
        return DeliveryResult.DELIVERED

    monkeypatch.setattr(notifications, "send_telegram_message", send)
    assert (
        notifications.notify_health(snapshot, now=NOW, settings=config, daily=outer_daily)
        is DeliveryResult.DELIVERED
    )
    assert blocked_results == [DeliveryResult.FAILED]
    assert len(messages) == 1
    assert "notification_failed reason=state_or_format" in caplog.text
    assert (
        notifications.notify_health(
            snapshot, now=NOW + timedelta(minutes=1), settings=config, daily=not outer_daily
        )
        is DeliveryResult.DELIVERED
    )
    for daily in (False, True):
        assert (
            notifications.notify_health(
                snapshot, now=NOW + timedelta(minutes=2), settings=config, daily=daily
            )
            is None
        )
    assert len(messages) == 2
