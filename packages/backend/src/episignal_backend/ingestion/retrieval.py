"""The gate-and-fetch pass: the only place a GDELT body is downloaded.

Discovery now stores a sighting with no body, so this pass is where a page is
paid for. It asks the keyword gate first, which is the whole point: a title
that shows no sign of a public health event never costs a page fetch.

Promotion, failure counting, and the retrieval_failed review path are the
existing ones, reached through the same repository the retry pass uses. This
module imports neither SQLAlchemy nor httpx.
"""

import logging
from dataclasses import dataclass

from episignal_backend.ingestion.keyword_gate import classify_title
from episignal_backend.ingestion.protocol import (
    DiscoveryConnector,
    DiscoveryRepository,
    RetrievalFailed,
)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BATCH_SIZE = 200
DEFAULT_WINDOW_HOURS = 72

logger = logging.getLogger("episignal_backend.ingestion.retrieval")


@dataclass(frozen=True)
class RetrievalResult:
    examined: int = 0
    filtered: int = 0
    retrieved: int = 0
    duplicates: int = 0
    redundant: int = 0
    still_failing: int = 0
    failed: int = 0


def run_retrieval(
    repository: DiscoveryRepository,
    connector: DiscoveryConnector,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> RetrievalResult:
    waiting = repository.gated_awaiting_retrieval(max_attempts=max_attempts, limit=batch_size)
    rules = repository.keyword_rules()
    if not rules:
        # Said out loud because an unseeded database and a deliberately empty
        # rule set look identical from the counts alone.
        logger.info("No active keyword rules; the gate is passing every title")

    filtered = 0
    retrieved = 0
    duplicates = 0
    redundant = 0
    still_failing = 0
    failed = 0

    for item in waiting:
        decision = classify_title(item.article.title, rules)
        if item.public_health_relevant is False or (
            item.public_health_relevant is not True and not decision.passed
        ):
            try:
                repository.record_filtered(item.signal_id)
                repository.commit()
            except Exception as error:
                repository.rollback()
                failed += 1
                logger.error(
                    "Could not record the filtering of %s (%s)",
                    item.article.canonical_url,
                    type(error).__name__,
                )
                continue
            filtered += 1
            continue

        primary_id = repository.title_duplicate_of(item.normalized_title, within_hours=window_hours)
        if primary_id is not None:
            try:
                # Free: a syndicated copy is recognised from its headline, so
                # the publisher is never asked for a page already held here.
                repository.mark_title_duplicate(item.signal_id, primary_id)
                repository.commit()
            except Exception as error:
                repository.rollback()
                failed += 1
                logger.error(
                    "Could not record title duplicate %s (%s)",
                    item.article.canonical_url,
                    type(error).__name__,
                )
                continue
            duplicates += 1
            continue

        try:
            signal = connector.retrieve(item.article, item.first_seen_at)
        except RetrievalFailed as reason:
            try:
                repository.record_failed_attempt(item.signal_id, max_attempts=max_attempts)
                repository.commit()
            except Exception as error:
                repository.rollback()
                failed += 1
                logger.error(
                    "Could not record a failed attempt for %s (%s)",
                    item.article.canonical_url,
                    type(error).__name__,
                )
            else:
                still_failing += 1
                logger.info("Retrieval of %s failed (%s)", item.article.canonical_url, reason)
            continue

        try:
            if repository.promote(item.signal_id, signal):
                retrieved += 1
            else:
                # Another row already carries this URL and hash. The bodyless
                # row is left exactly as it was: a spare row costs less than
                # deleting one on a guess.
                redundant += 1
            repository.commit()
        except Exception as error:
            repository.rollback()
            failed += 1
            logger.error(
                "Could not store the body of %s (%s)",
                item.article.canonical_url,
                type(error).__name__,
            )

    return RetrievalResult(
        examined=len(waiting),
        filtered=filtered,
        retrieved=retrieved,
        duplicates=duplicates,
        redundant=redundant,
        still_failing=still_failing,
        failed=failed,
    )
