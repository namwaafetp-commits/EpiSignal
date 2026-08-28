"""Bounded, auditable operation to requeue extraction-failed signals from needs_review.

Signals that reached needs_review due to model exhaustion or extraction failure
are returned to CLASSIFIED so that the extraction pass can retry them with
structured outputs and the refreshed ladder.

Corrupted signals (including 852aa204-846d-4aa6-a256-82c187fdeaef), discovery
stubs with missing raw text, and event assembly failures are strictly excluded.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from episignal_backend.db.types import AiPurpose, ProcessingStatus
from episignal_backend.ingestion.fingerprint import verify_content_hash
from episignal_backend.models import AiRequest, Signal

logger = logging.getLogger("episignal_backend.ai.requeue")

QUARANTINED_SIGNAL_IDS: frozenset[UUID] = frozenset(
    [
        UUID("852aa204-846d-4aa6-a256-82c187fdeaef"),
    ]
)


@dataclass(frozen=True)
class RequeueResult:
    scanned: int
    requeued: int
    quarantined_skipped: int
    invalid_hash_skipped: int
    non_extraction_skipped: int
    requeued_ids: tuple[UUID, ...]


def requeue_extraction_backlog(session: Session, *, limit: int | None = None) -> RequeueResult:
    stmt = (
        select(Signal)
        .where(
            Signal.processing_status == ProcessingStatus.NEEDS_REVIEW,
        )
        .order_by(Signal.first_seen_at)
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    signals = list(session.execute(stmt).scalars().all())

    requeued_ids: list[UUID] = []
    quarantined_skipped = 0
    invalid_hash_skipped = 0
    non_extraction_skipped = 0

    for signal in signals:
        # 1. Explicit quarantine check
        if signal.id in QUARANTINED_SIGNAL_IDS:
            quarantined_skipped += 1
            logger.info("Signal %s skipped from requeue (explicitly quarantined)", signal.id)
            continue

        # 2. Content integrity check (title + raw_text vs content_hash)
        if not signal.raw_text or not verify_content_hash(
            signal.title, signal.raw_text, signal.content_hash
        ):
            invalid_hash_skipped += 1
            logger.warning(
                "Signal %s skipped from requeue (hash integrity failure or missing raw text)",
                signal.id,
            )
            continue

        # 3. Check if signal is classified as public health relevant with extraction attempts
        has_extraction_request = session.execute(
            select(AiRequest.id)
            .where(
                AiRequest.signal_id == signal.id,
                AiRequest.purpose == AiPurpose.EXTRACTION,
            )
            .limit(1)
        ).scalar_one_or_none()

        if (
            signal.public_health_relevant is not True
            or signal.ai_extraction is not None
            or not has_extraction_request
        ):
            non_extraction_skipped += 1
            logger.info(
                "Signal %s skipped from requeue (not an unextracted relevant signal)",
                signal.id,
            )
            continue

        # 4. Safe to requeue: update status to CLASSIFIED
        session.execute(
            update(Signal)
            .where(Signal.id == signal.id)
            .values(processing_status=ProcessingStatus.CLASSIFIED)
        )
        requeued_ids.append(signal.id)
        logger.info("Signal %s requeued for extraction: '%s'", signal.id, signal.title)

    session.commit()

    return RequeueResult(
        scanned=len(signals),
        requeued=len(requeued_ids),
        quarantined_skipped=quarantined_skipped,
        invalid_hash_skipped=invalid_hash_skipped,
        non_extraction_skipped=non_extraction_skipped,
        requeued_ids=tuple(requeued_ids),
    )
