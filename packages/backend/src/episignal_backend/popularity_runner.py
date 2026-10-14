"""Entry point for the scheduled Briefing popularity aggregate sync."""

import logging

from episignal_backend.briefing.popularity_sync import sync_event_popularity
from episignal_backend.briefing.umami import UmamiApiError, UmamiClient
from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope

logger = logging.getLogger(__name__)


def main() -> int:
    settings = get_settings()
    if not all(
        (
            settings.umami_base_url.strip(),
            settings.umami_website_id.strip(),
            settings.umami_api_token.get_secret_value().strip(),
        )
    ):
        logger.error("Popularity sync is not configured")
        return 1
    try:
        with (
            UmamiClient(
                base_url=settings.umami_base_url,
                website_id=settings.umami_website_id,
                api_token=settings.umami_api_token.get_secret_value(),
                timeout=settings.umami_timeout_seconds,
            ) as client,
            session_scope() as session,
        ):
            result = sync_event_popularity(session, client)
    except UmamiApiError as error:
        logger.error("Popularity sync failed (%s)", type(error).__name__)
        return 1
    except Exception as error:
        logger.error("Popularity sync failed (%s)", type(error).__name__)
        return 1
    logger.info(
        "Popularity sync completed impressions=%d opens=%d skipped_invalid_ids=%d",
        result.impressions_total,
        result.opens_total,
        result.skipped_invalid_ids,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
