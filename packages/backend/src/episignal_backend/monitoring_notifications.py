"""Format, compare delivery checkpoints, and send existing health summaries."""

import hashlib
import json
import logging
from datetime import datetime

from episignal_backend.config import Settings
from episignal_backend.monitoring_messages import (
    abnormal_fingerprint,
    format_abnormal_alert,
    format_daily_report,
    format_recovery,
)
from episignal_backend.notification_state import NotificationState, locked_state
from episignal_backend.operational_monitoring import BANGKOK, HealthStatus, HealthSummary
from episignal_backend.telegram import DeliveryResult, send_telegram_message, telegram_configured

logger = logging.getLogger(__name__)
ABNORMAL = (HealthStatus.WARNING, HealthStatus.CRITICAL)


def notify_health(
    summary: HealthSummary, *, now: datetime, settings: Settings, daily: bool = False
) -> DeliveryResult | None:
    """None means suppressed; delivery failures never escape into monitoring.

    Daily and transition checkpoints are independent. Observe newer snapshots
    even after a failed send. A new observation invalidates the old acknowledgement;
    the new checkpoint is marked delivered only after Telegram acknowledges it.
    """
    if not telegram_configured(settings) or settings.telegram_state_path is None:
        logger.info("telegram_notifications_disabled reason=configuration")
        return DeliveryResult.DISABLED
    destination = hashlib.sha256(
        json.dumps(
            [
                settings.telegram_bot_token.get_secret_value().strip(),
                settings.telegram_chat_id.get_secret_value().strip(),
            ]
        ).encode()
    ).hexdigest()
    channel = f"{'daily' if daily else 'alerts'}:{destination}"
    try:
        if now.utcoffset() is None:
            raise ValueError("timezone required")
        with locked_state(settings.telegram_state_path, channel) as state:
            if now.timestamp() < state.observed_at:
                logger.info("notification_suppressed reason=stale_snapshot")
                return None
            state.observed_at = now.timestamp()
            if daily:
                day = now.astimezone(BANGKOK).date().isoformat()
                if state.delivered == day:
                    logger.info("daily_report_suppressed reason=already_delivered")
                    return None
                return _deliver(
                    format_daily_report(summary, now=now),
                    event="daily_report",
                    checkpoint=day,
                    state=state,
                    settings=settings,
                )
            return _notify_transition(summary, now=now, state=state, settings=settings)
    except Exception:
        logger.warning("notification_failed reason=state_or_format")
        return DeliveryResult.FAILED


def _notify_transition(
    summary: HealthSummary, *, now: datetime, state: NotificationState, settings: Settings
) -> DeliveryResult | None:
    previous_status = HealthStatus.HEALTHY
    if state.observed:
        previous, _ = json.loads(state.observed)
        previous_status = HealthStatus(previous)
    if summary.status in ABNORMAL:
        fingerprint = abnormal_fingerprint(summary)
        checkpoint = json.dumps([summary.status.value, fingerprint])
        if state.observed != checkpoint:
            state.observed = checkpoint
            state.delivered = ""
        state.recovery_from = ""
        if state.delivered == checkpoint:
            logger.info("alert_suppressed reason=unchanged_abnormal_state")
            return None
        logger.info(
            "abnormal_transition_detected previous=%s current=%s",
            previous_status.value,
            summary.status.value,
        )
        return _deliver(
            format_abnormal_alert(summary, now=now),
            event="alert",
            checkpoint=checkpoint,
            state=state,
            settings=settings,
        )
    if summary.status is HealthStatus.HEALTHY:
        if previous_status in ABNORMAL:
            state.observed = json.dumps([HealthStatus.HEALTHY.value, ""])
            state.delivered = ""
            state.recovery_from = previous_status.value
        if not state.recovery_from:
            return None
        recovery_from = HealthStatus(state.recovery_from)
        logger.info("recovery_detected previous=%s", recovery_from.value)
        result = _deliver(
            format_recovery(summary, previous_status=recovery_from, now=now),
            event="recovery",
            checkpoint="",
            state=state,
            settings=settings,
        )
        if result is DeliveryResult.DELIVERED:
            state.recovery_from = ""
        return result
    return None


def _deliver(
    message: str,
    *,
    event: str,
    checkpoint: str,
    state: NotificationState,
    settings: Settings,
) -> DeliveryResult:
    logger.info("%s_attempted", event)
    result = send_telegram_message(message, settings=settings)
    if result is DeliveryResult.DELIVERED:
        state.delivered = checkpoint
        logger.info("%s_delivered", event)
    else:
        logger.warning("%s_failed result=%s", event, result.value)
    return result
