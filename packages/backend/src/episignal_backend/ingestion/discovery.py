"""Discovery decisions.

This module imports neither SQLAlchemy nor httpx. It depends on the two
Protocols in `protocol.py`, which is what makes every decision below testable
with in-memory fakes and no credentials.

The ordering here is the whole point of the module: GDELT names far more
articles than are worth fetching, so already-stored URLs are dropped before any
publisher connection is opened, and what remains is capped.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from episignal_backend.ingestion.documents import DiscoveredArticle, TimeWindow
from episignal_backend.ingestion.protocol import (
    DiscoveryConnector,
    DiscoveryRepository,
    RetrievalFailed,
)

DEFAULT_WINDOW_MINUTES = 20
DEFAULT_MAX_ARTICLES = 200
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BATCH = 50

logger = logging.getLogger("episignal_backend.ingestion.discovery")


@dataclass(frozen=True)
class DiscoveryResult:
    rules_run: int = 0
    rules_failed: int = 0
    discovered: int = 0
    duplicate: int = 0
    deferred: int = 0
    stored: int = 0
    needs_review: int = 0
    failed: int = 0


@dataclass(frozen=True)
class RetryResult:
    attempted: int = 0
    promoted: int = 0
    still_failing: int = 0
    redundant: int = 0
    failed: int = 0


def run_retry(
    repository: DiscoveryRepository,
    connector: DiscoveryConnector,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    batch_size: int = DEFAULT_RETRY_BATCH,
) -> RetryResult:
    return RetryResult()


def run_discovery(
    repository: DiscoveryRepository,
    connector: DiscoveryConnector,
    *,
    now: datetime | None = None,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    max_articles: int = DEFAULT_MAX_ARTICLES,
) -> DiscoveryResult:
    moment = now or datetime.now(UTC)
    window = TimeWindow(start=moment - timedelta(minutes=window_minutes), end=moment)

    rules = repository.active_rules()
    rules_failed = 0
    discovered: dict[str, DiscoveredArticle] = {}

    for rule in rules:
        try:
            found = connector.discover(rule, window)
        except Exception as error:
            # One rate-limited rule must not discard the other forty-nine.
            rules_failed += 1
            logger.warning(
                "Discovery rule %s failed (%s)",
                rule.label,
                type(error).__name__,
            )
            continue
        for article in found:
            # Within a run the same story arrives under several rules; the first
            # sighting keeps the rule that found it.
            discovered.setdefault(article.canonical_url, article)

    already_stored = repository.seen_urls(tuple(discovered))
    candidates = [
        article
        for canonical_url, article in discovered.items()
        if canonical_url not in already_stored
    ]
    # Oldest first, so a burst of fresh articles never starves a discovery that
    # has already been waiting for a slot.
    candidates.sort(key=lambda article: article.gdelt_seen_at)
    selected = candidates[:max_articles]

    stored = 0
    needs_review = 0
    failed = 0

    for article in selected:
        first_seen = repository.first_seen_at(article.canonical_url) or moment
        try:
            signal = connector.retrieve(article, first_seen)
        except RetrievalFailed as reason:
            signal = connector.stub(article, first_seen)
            logger.info(
                "Stored %s as needs_review (%s)",
                article.canonical_url,
                reason,
            )

        try:
            source_id = repository.publisher_source_id(signal.publisher)
            repository.add(signal, source_id)
            repository.commit()
        except Exception as error:
            repository.rollback()
            failed += 1
            logger.error(
                "Could not store %s (%s)",
                article.canonical_url,
                type(error).__name__,
            )
            continue

        if signal.raw_text is None:
            needs_review += 1
        else:
            stored += 1

    return DiscoveryResult(
        rules_run=len(rules),
        rules_failed=rules_failed,
        discovered=len(discovered),
        duplicate=len(already_stored),
        deferred=len(candidates) - len(selected),
        stored=stored,
        needs_review=needs_review,
        failed=failed,
    )
