"""Stage 0 deduplication: resolve syndicated copies to one primary.

The normal scheduled pass runs before retrieval and therefore uses only
canonical URL, normalized title, and near-exact title metadata. The standalone
body-aware pass remains available after retrieval for callers that explicitly
need content similarity. The conservative direction is deliberate: two
outlets reporting the same outbreak independently are corroboration, which is
the raw material of the evidence score.

This module imports neither SQLAlchemy nor httpx.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from rapidfuzz import fuzz

from episignal_backend.ingestion.documents import ComparableSignal
from episignal_backend.ingestion.normalize_title import normalize_title
from episignal_backend.ingestion.protocol import DedupeRepository
from episignal_backend.ingestion.similarity import body_similarity, title_similarity

DEFAULT_WINDOW_HOURS = 72
DEFAULT_BATCH_SIZE = 200

logger = logging.getLogger("episignal_backend.ingestion.dedupe")


@dataclass(frozen=True)
class DedupeThresholds:
    title: float = 0.90
    body: float = 0.80
    shingle_size: int = 5
    # Near-exact RapidFuzz rule (lean MVP Section 9): title similarity above
    # this score within a short publication window is a syndicated copy. The
    # upper bound is deliberately exclusive of an exact title match: an exact
    # match keeps the verified conservative path (identical headline with a
    # genuinely independent body is corroboration, not a duplicate).
    near_exact_title: float = 92.0
    near_exact_window_hours: int = 48

    def __post_init__(self) -> None:
        if not 0.0 <= self.near_exact_title <= 100.0:
            raise ValueError("near_exact_title must be between 0 and 100")


@dataclass(frozen=True)
class DedupeResult:
    examined: int = 0
    primaries: int = 0
    duplicates: int = 0
    failed: int = 0


def precedes(left: ComparableSignal, right: ComparableSignal) -> bool:
    """A total order, so the choice of primary is stable and cycles impossible.

    Earliest sighting first: the radar exists to measure detection lead time, so
    the row that earned the lead keeps it. Publisher credibility cannot break
    the tie, because every GDELT-registered publisher starts as unknown.
    """
    if left.first_seen_at != right.first_seen_at:
        return left.first_seen_at < right.first_seen_at
    if left.published_at != right.published_at:
        if left.published_at is None:
            return False
        if right.published_at is None:
            return True
        return left.published_at < right.published_at
    return str(left.id) < str(right.id)


def near_exact_title_match(
    signal: ComparableSignal,
    candidate: ComparableSignal,
    thresholds: DedupeThresholds,
) -> bool:
    """Whether two titles are near-exact syndications of one report.

    RapidFuzz ratio on the raw titles, not the normalized form, because the
    stored normalized title already strips the masthead suffix that is exactly
    what syndication differs by. Requires both publication times within the
    window; an unknown publication time never matches near-exactly.
    """
    if signal.published_at is None or candidate.published_at is None:
        return False
    gap = abs(signal.published_at - candidate.published_at)
    if gap > timedelta(hours=thresholds.near_exact_window_hours):
        return False
    ratio = fuzz.ratio(signal.title, candidate.title)
    return thresholds.near_exact_title <= ratio < 100.0


def matches(
    signal: ComparableSignal,
    candidate: ComparableSignal,
    thresholds: DedupeThresholds,
    *,
    metadata_only: bool = False,
) -> bool:
    if metadata_only:
        if signal.canonical_url == candidate.canonical_url:
            return True
        if normalize_title(signal.title) == normalize_title(candidate.title):
            return True
        gap = abs(signal.first_seen_at - candidate.first_seen_at)
        return (
            gap <= timedelta(hours=thresholds.near_exact_window_hours)
            and thresholds.near_exact_title <= fuzz.ratio(signal.title, candidate.title) < 100.0
        )
    if candidate.content_hash == signal.content_hash:
        return True
    if near_exact_title_match(signal, candidate, thresholds):
        return True
    # Title first: it is far cheaper, and a body comparison that the title
    # already rules out is work no pair needs.
    if title_similarity(signal.title, candidate.title) < thresholds.title:
        return False
    similarity = body_similarity(signal.raw_text, candidate.raw_text, size=thresholds.shingle_size)
    return similarity >= thresholds.body


def run_dedupe(
    repository: DedupeRepository,
    *,
    thresholds: DedupeThresholds | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    metadata_only: bool = False,
) -> DedupeResult:
    limits = thresholds or DedupeThresholds()
    pending = repository.pending(limit=batch_size)

    primaries = 0
    duplicates = 0
    failed = 0

    for signal in pending:
        try:
            primary: ComparableSignal | None = None
            for candidate in repository.candidates(signal, window_hours=window_hours):
                if candidate.id == signal.id:
                    continue
                if not matches(signal, candidate, limits, metadata_only=metadata_only):
                    continue
                if primary is None or precedes(candidate, primary):
                    primary = candidate

            if primary is not None and precedes(primary, signal):
                # Flatten: a pointer must never lead to another pointer, or
                # reading the family back would need a recursive query.
                repository.mark_duplicate(signal.id, repository.primary_of(primary.id))
                duplicates += 1
            else:
                repository.mark_normalized(signal.id)
                primaries += 1
            repository.commit()
        except Exception as error:
            repository.rollback()
            failed += 1
            logger.error(
                "Could not resolve %s (%s)",
                signal.canonical_url,
                type(error).__name__,
            )

    return DedupeResult(
        examined=len(pending),
        primaries=primaries,
        duplicates=duplicates,
        failed=failed,
    )
