"""Exercise the documented proposal against the unchanged production evaluator."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from episignal_backend import monitoring_notifications as notifications
from episignal_backend.config import Settings
from episignal_backend.db.types import PipelineRunStatus, PipelineTrigger
from episignal_backend.operational_monitoring import (
    BANGKOK,
    HealthStatus,
    PipelineHealthRecord,
    PipelineRunCoverageRecord,
    summarize_health,
)
from episignal_backend.telegram import DeliveryResult

DAY = datetime(2026, 9, 7, tzinfo=BANGKOK)
DOC = Path(__file__).resolve().parents[3] / "docs" / "telegram-monitoring.md"


def at(hour, minute=0):
    return DAY + timedelta(hours=hour, minutes=minute)


def health(now, *, runtime=6, missed=None, late=None, failing_stage=None):
    """Synthetic scheduled starts and completed telemetry, never provider calls.

    Six minutes is a representative synthetic runtime, not a VPS measurement.
    Include real scheduled coverage evidence; never override coverage or status.
    """
    records = []
    coverage = []
    for hour in range(-24, 49):
        started = at(hour)
        if started > now or hour == missed:
            continue
        duration = 40 if hour == late else runtime
        finished = started + timedelta(minutes=duration)
        completed = finished <= now
        run_id = UUID(int=hour + 100)
        coverage.append(
            PipelineRunCoverageRecord(
                run_id=run_id,
                started_at=started,
                finished_at=finished if completed else None,
                status=PipelineRunStatus.SUCCEEDED if completed else PipelineRunStatus.RUNNING,
                trigger=PipelineTrigger.SCHEDULED,
            )
        )
        if not completed:
            continue
        record = PipelineHealthRecord(
            run_id=run_id,
            started_at=started,
            finished_at=finished,
            status=PipelineRunStatus.SUCCEEDED,
            trigger=PipelineTrigger.SCHEDULED,
            duration_sec=duration * 60,
            discovered=100,
            deepseek_relevant=0,
            deepseek_requested=100,
            deepseek_success=100,
            retrieval_requested=100,
            retrieval_success=100,
            gemini_requested=100,
            gemini_success=100,
            grouping_requested=100,
            grouping_success=100,
            mistral_requested=100,
            mistral_success=100,
            fatal_error_count=0,
        )
        if hour == 8 and failing_stage == "deepseek":
            record = replace(record, deepseek_success=70)
        if hour == 8 and failing_stage == "retrieval":
            record = replace(record, retrieval_requested=1000, retrieval_success=0)
        records.append(record)
    return summarize_health(records, now=now, coverage_runs=coverage)


def cron_minutes(mode):
    """Read the actual documented five-field UTC proposal, not a second schedule."""
    result = []
    for line in DOC.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 6 or not fields[0][0].isdigit() and fields[0] != "*/5":
            continue
        if mode not in fields:
            continue
        minute, hour, day, month, weekday = fields[:5]
        assert (day, month, weekday) == ("*", "*", "*")
        minutes = range(0, 60, 5) if minute == "*/5" else map(int, minute.split(","))
        hours = range(24) if hour == "*" else [int(hour)]
        for m in minutes:
            for h in hours:
                result.append((h, m))
    assert result, f"No documented cron entry for {mode}"
    return result


def proposal_instants(mode):
    utc_day = at(8).astimezone(UTC).replace(hour=0, minute=0)
    return sorted(utc_day + timedelta(hours=h, minutes=m) for h, m in cron_minutes(mode))


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        database_url="postgresql://test:test@localhost/test",
        telegram_bot_token="123:fake",
        telegram_chat_id="-123",
        telegram_state_path=tmp_path / "state.sqlite3",
    )
    send = Mock(return_value=DeliveryResult.DELIVERED)
    monkeypatch.setattr(notifications, "send_telegram_message", send)
    return settings, send


def test_five_minute_polling_reproduces_routine_freshness_cycles(delivery):
    settings, send = delivery
    samples = []
    for minutes in range(10, 191, 5):
        now = at(8, minutes)
        snapshot = health(now)
        samples.append((now.strftime("%H:%M"), snapshot.freshness_minutes, snapshot.status))
        notifications.notify_health(snapshot, now=now, settings=settings)
    assert ("08:35", 29, HealthStatus.HEALTHY) in samples
    assert ("08:40", 34, HealthStatus.WARNING) in samples
    assert ("09:05", 59, HealthStatus.WARNING) in samples
    assert ("09:10", 4, HealthStatus.HEALTHY) in samples
    headers = [call.args[0].splitlines()[0] for call in send.call_args_list]
    assert headers == ["🟡 EpiSignal WARNING", "🟢 EpiSignal RECOVERED"] * 3


@pytest.mark.parametrize("runtime", [0.1, 6, 14.9])
def test_proposed_post_run_and_watchdog_times_keep_normal_hourly_runs_quiet(delivery, runtime):
    settings, send = delivery
    watchdog = [now for now in proposal_instants("--notify") if at(8) <= now < at(11)]
    assert watchdog
    instants = sorted(watchdog + [at(hour, runtime) for hour in range(8, 11)])
    for now in instants:
        snapshot = health(now, runtime=runtime)
        assert snapshot.status is HealthStatus.HEALTHY, (now, snapshot)
        notifications.notify_health(snapshot, now=now, settings=settings)
    send.assert_not_called()


def test_proposed_cron_has_disjoint_modes_and_daily_after_normal_completion():
    alert = set(cron_minutes("--notify"))
    daily = set(cron_minutes("--daily-report"))
    assert not alert & daily
    assert daily == {(1, 20), (1, 21)}  # one report; the second invocation is a bounded retry
    assert alert == {(hour, minute) for hour in range(24) for minute in (16, 26)}
    for instant in proposal_instants("--daily-report"):
        assert instant.astimezone(BANGKOK).hour == 8
        assert health(instant, runtime=14.9).status is HealthStatus.HEALTHY


def test_missed_hour_is_critical_at_first_watchdog_and_does_not_repeat(delivery):
    settings, send = delivery
    checks = [now for now in proposal_instants("--notify") if at(8) <= now < at(9)]
    assert checks[0] == at(8, 16)
    first = health(checks[0], missed=8)
    assert first.freshness_minutes == 70
    assert first.freshness_status is HealthStatus.CRITICAL
    assert first.coverage_status is HealthStatus.CRITICAL
    for now in checks:
        notifications.notify_health(health(now, missed=8), now=now, settings=settings)
    send.assert_called_once()
    assert send.call_args.args[0].startswith("🔴 EpiSignal CRITICAL")
    # A completed next run fixes freshness, not the day's missing scheduled slot.
    assert health(at(9, 6), missed=8).status is HealthStatus.CRITICAL
    for now in [at(24, 16), at(24, 26)]:
        recovered = health(now, missed=8)
        assert recovered.status is HealthStatus.HEALTHY
        notifications.notify_health(recovered, now=now, settings=settings)
    assert send.call_count == 2
    assert "RECOVERED" in send.call_args.args[0]


def test_late_run_is_detected_while_active_then_recovers_once_after_completion(delivery):
    settings, send = delivery
    for now in [at(8, 16), at(8, 26)]:
        snapshot = health(now, late=8)
        assert snapshot.coverage_status is HealthStatus.HEALTHY
        assert snapshot.freshness_status is HealthStatus.CRITICAL
        notifications.notify_health(snapshot, now=now, settings=settings)
    send.assert_called_once()
    for now in [at(8, 40), at(9, 16)]:
        snapshot = health(now, late=8)
        assert snapshot.status is HealthStatus.HEALTHY
        notifications.notify_health(snapshot, now=now, settings=settings)
    assert send.call_count == 2
    assert "RECOVERED" in send.call_args.args[0]


@pytest.mark.parametrize(
    "stage,severity", [("deepseek", HealthStatus.WARNING), ("retrieval", HealthStatus.CRITICAL)]
)
def test_real_stage_status_alerts_at_post_run_and_watchdog_deduplicates(delivery, stage, severity):
    settings, send = delivery
    for now in [at(8, 6), at(8, 16), at(8, 26)]:
        snapshot = health(now, failing_stage=stage)
        assert snapshot.freshness_status is HealthStatus.HEALTHY
        assert snapshot.stage_success_rates[stage].status is severity
        assert snapshot.status is severity
        notifications.notify_health(snapshot, now=now, settings=settings)
    send.assert_called_once()
    assert severity.value.upper() in send.call_args.args[0].splitlines()[0]


def test_failed_post_run_alert_retries_at_next_eligible_watchdog(delivery):
    settings, send = delivery
    send.side_effect = [DeliveryResult.FAILED, DeliveryResult.DELIVERED]
    times = [at(8, 6)] + [now for now in proposal_instants("--notify") if at(8) <= now < at(9)]
    results = [
        notifications.notify_health(
            health(now, failing_stage="deepseek"), now=now, settings=settings
        )
        for now in times
    ]
    assert results == [DeliveryResult.FAILED, DeliveryResult.DELIVERED, None]
    assert send.call_count == 2
