"""Small plain-text Telegram transport; never expose credential-bearing URLs."""

import json
import logging
from enum import StrEnum
from http.client import HTTPSConnection

from episignal_backend.config import Settings, get_settings

logger = logging.getLogger(__name__)


class DeliveryResult(StrEnum):
    DELIVERED = "delivered"
    FAILED = "failed"
    DISABLED = "disabled"


def telegram_configured(settings: Settings) -> bool:
    return bool(
        settings.telegram_bot_token.get_secret_value().strip()
        and settings.telegram_chat_id.get_secret_value().strip()
    )


def send_telegram_message(text: str, *, settings: Settings | None = None) -> DeliveryResult:
    settings = settings or get_settings()
    if not telegram_configured(settings):
        logger.info("telegram_notifications_disabled")
        return DeliveryResult.DISABLED
    if not text or len(text.encode("utf-16-le")) // 2 > 4096:
        logger.warning("telegram_delivery_failed reason=message_length")
        return DeliveryResult.FAILED
    connection = HTTPSConnection("api.telegram.org", timeout=10)
    try:
        # http.client does not log request URLs (unlike httpx at INFO) or follow
        # redirects. Keep its debug level at the default zero.
        connection.request(
            "POST",
            f"/bot{settings.telegram_bot_token.get_secret_value().strip()}/sendMessage",
            body=json.dumps(
                {
                    "chat_id": settings.telegram_chat_id.get_secret_value().strip(),
                    "text": text,
                    "link_preview_options": {"is_disabled": True},
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        if response.status != 200:
            logger.warning("telegram_delivery_failed reason=http status=%d", response.status)
            return DeliveryResult.FAILED
        payload = json.loads(response.read(65537))
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            logger.warning("telegram_delivery_failed reason=api")
            return DeliveryResult.FAILED
        return DeliveryResult.DELIVERED
    except Exception:
        # Exceptions may embed bot tokens, request paths, bodies or chat ids.
        logger.warning("telegram_delivery_failed reason=transport")
        return DeliveryResult.FAILED
    finally:
        connection.close()
