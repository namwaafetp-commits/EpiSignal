"""The classification-gated fetch pass: the only place a GDELT body is downloaded.

Discovery stores a sighting with no body, so this pass is where a page is paid
for. Classification is the sole production retrieval gate: only an accepted
``public_health_relevant=True`` decision may pay for a page.

Promotion, failure counting, and the retrieval_failed review path are the
existing ones, reached through the same repository the retry pass uses. This
module imports neither SQLAlchemy nor httpx.
"""

import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from episignal_backend.diagnostics import FailureCategory, classify_retrieval_failure
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
    unclassified: int = 0
    filtered: int = 0
    retrieved: int = 0
    duplicates: int = 0
    redundant: int = 0
    still_failing: int = 0
    failed: int = 0
    failure_categories: dict[str, int] = field(default_factory=dict)
    failure_domains: dict[str, int] = field(default_factory=dict)


def run_retrieval(
    repository: DiscoveryRepository,
    connector: DiscoveryConnector,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    signal_ids: Sequence[UUID] | None = None,
) -> RetrievalResult:
    if signal_ids is None:
        waiting = repository.gated_awaiting_retrieval(max_attempts=max_attempts, limit=batch_size)
    else:
        waiting = repository.gated_awaiting_retrieval(
            max_attempts=max_attempts, limit=batch_size, signal_ids=signal_ids
        )
    filtered = 0
    retrieved = 0
    duplicates = 0
    redundant = 0
    still_failing = 0
    failed = 0
    unclassified = 0
    failure_categories: Counter[str] = Counter()
    failure_domains: Counter[str] = Counter()

    for item in waiting:
        if item.public_health_relevant is None:
            # Classification has not completed, or its provider was unavailable
            # or guarded. Leave it untouched for the next scheduled run.
            unclassified += 1
            continue
        if item.public_health_relevant is False:
            try:
                repository.record_filtered(item.signal_id)
                repository.commit()
            except Exception as error:
                repository.rollback()
                failed += 1
                failure_categories[FailureCategory.STORAGE_FAILURE.value] += 1
                failure_domains[item.article.domain] += 1
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
                failure_categories[FailureCategory.STORAGE_FAILURE.value] += 1
                failure_domains[item.article.domain] += 1
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
                failure_categories[FailureCategory.STORAGE_FAILURE.value] += 1
                failure_domains[item.article.domain] += 1
                logger.error(
                    "Could not record a failed attempt for %s (%s)",
                    item.article.canonical_url,
                    type(error).__name__,
                )
            else:
                still_failing += 1
                failure_domains[item.article.domain] += 1
                category = classify_retrieval_failure(
                    str(reason), category=getattr(reason, "category", None)
                )
                failure_categories[category.value] += 1
                logger.info(
                    "Retrieval of %s failed (%s)",
                    item.article.canonical_url,
                    category.value,
                )
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
            failure_domains[item.article.domain] += 1
            logger.error(
                "Could not store the body of %s (%s)",
                item.article.canonical_url,
                type(error).__name__,
            )

    return RetrievalResult(
        examined=len(waiting),
        unclassified=unclassified,
        filtered=filtered,
        retrieved=retrieved,
        duplicates=duplicates,
        redundant=redundant,
        still_failing=still_failing,
        failed=failed,
        failure_categories=dict(failure_categories),
        failure_domains=dict(failure_domains),
    )
