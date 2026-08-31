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

from episignal_backend.ingestion.documents import DiscoveredArticle, Rejection, TimeWindow
from episignal_backend.ingestion.filtering import compile_rules, evaluate
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
    rules_invalid: int = 0
    discovered: int = 0
    duplicate: int = 0
    rejected: int = 0
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
    filters = compile_rules(repository.filter_rules())
    if not filters.titles and not filters.domains:
        # A valid configuration, not an error. Said out loud because the
        # alternative reading — a seeding accident — looks identical from the
        # counts alone.
        logger.info("No active filter rules; discovery is running unfiltered")
    rules_failed = 0
    failed = 0
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
    surviving = [
        article
        for canonical_url, article in discovered.items()
        if canonical_url not in already_stored
    ]

    # Gate one. Before the cap, so the run's budget is spent on articles worth
    # having rather than on articles about to be discarded.
    candidates: list[DiscoveredArticle] = []
    rejected = 0
    for article in surviving:
        filter_rule = evaluate(article, filters)
        if filter_rule is None:
            candidates.append(article)
            continue
        try:
            repository.record_rejection(
                Rejection(
                    url=article.url,
                    canonical_url=article.canonical_url,
                    title=article.title,
                    domain=article.domain,
                    gdelt_seen_at=article.gdelt_seen_at,
                    rejected_at=moment,
                    filter_rule_id=filter_rule.id,
                )
            )
            repository.commit()
        except Exception as error:
            repository.rollback()
            failed += 1
            # Keep it: losing the audit row must not also lose the article.
            candidates.append(article)
            logger.error(
                "Could not record the rejection of %s (%s)",
                article.canonical_url,
                type(error).__name__,
            )
            continue
        rejected += 1
        logger.info("Rejected %s (%s)", article.canonical_url, filter_rule.label)

    # Oldest first, so a burst of fresh articles never starves a discovery that
    # has already been waiting for a slot.
    candidates.sort(key=lambda article: article.gdelt_seen_at)
    selected = candidates[:max_articles]

    stored = 0
    for article in selected:
        first_seen = repository.first_seen_at(article.canonical_url) or moment
        # Retrieval moved behind the keyword gate: a body is downloaded in the
        # retrieve stage, and only for an article whose title earned it.
        signal = connector.defer(article, first_seen)

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

        stored += 1

    return DiscoveryResult(
        rules_run=len(rules),
        rules_failed=rules_failed,
        rules_invalid=filters.invalid,
        discovered=len(discovered),
        duplicate=len(already_stored),
        rejected=rejected,
        deferred=len(candidates) - len(selected),
        stored=stored,
        needs_review=0,
        failed=failed,
    )


def run_retry(
    repository: DiscoveryRepository,
    connector: DiscoveryConnector,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    batch_size: int = DEFAULT_RETRY_BATCH,
) -> RetryResult:
    """Give stubs another chance at their pages.

    Retry cannot come from re-discovery: the same article found again hashes
    identically and is dropped by the seen-URL check, so the stub rows have to
    be read back. The attempt budget is enforced in the selection query, which
    is what stops an unreachable page being fetched forever.
    """
    stubs = repository.stubs_awaiting_retrieval(max_attempts=max_attempts, limit=batch_size)

    promoted = 0
    still_failing = 0
    redundant = 0
    failed = 0

    for waiting in stubs:
        try:
            signal = connector.retrieve(waiting.article, waiting.first_seen_at)
        except RetrievalFailed as reason:
            try:
                repository.record_failed_attempt(waiting.signal_id, max_attempts=max_attempts)
                repository.commit()
            except Exception as error:
                repository.rollback()
                failed += 1
                logger.error(
                    "Could not record a failed attempt for %s (%s)",
                    waiting.article.canonical_url,
                    type(error).__name__,
                )
            else:
                still_failing += 1
                logger.info(
                    "Retry of %s still failing (%s)",
                    waiting.article.canonical_url,
                    reason,
                )
            continue

        try:
            if repository.promote(waiting.signal_id, signal):
                promoted += 1
            else:
                # The URL already carries this content under another row, so the
                # stub is redundant rather than promotable. It is left in place.
                redundant += 1
            repository.commit()
        except Exception as error:
            repository.rollback()
            failed += 1
            logger.error(
                "Could not promote %s (%s)",
                waiting.article.canonical_url,
                type(error).__name__,
            )

    return RetryResult(
        attempted=len(stubs),
        promoted=promoted,
        still_failing=still_failing,
        redundant=redundant,
        failed=failed,
    )
