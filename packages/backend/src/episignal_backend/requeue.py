"""One-time recovery of historical review rows for the lean MVP."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from episignal_backend.db.types import ProcessingStatus
from episignal_backend.events.repository import read_stored_extraction
from episignal_backend.models import Signal


@dataclass(frozen=True)
class RequeueResult:
    examined: int = 0
    requeued: int = 0


def requeue_historical_extractions(session: Session, *, limit: int | None = None) -> RequeueResult:
    """Return eligible historical review rows to ``extracted`` only.

    This deliberately validates stored JSON in Python. PostgreSQL can check
    presence, but not the version-tolerant extraction contract used by readers.
    """
    statement = (
        select(Signal)
        .where(
            Signal.processing_status == ProcessingStatus.NEEDS_REVIEW,
            Signal.ai_extraction.is_not(None),
            Signal.duplicate_of_signal_id.is_(None),
            Signal.public_health_relevant.is_not(False),
        )
        .order_by(Signal.first_seen_at, Signal.id)
    )
    if limit is not None:
        statement = statement.limit(limit)

    rows = session.execute(statement).scalars().all()
    requeued = 0
    for signal in rows:
        if signal.duplicate_of_signal_id is not None or signal.public_health_relevant is False:
            continue
        if read_stored_extraction(signal.ai_extraction) is None:
            continue
        signal.processing_status = ProcessingStatus.EXTRACTED
        requeued += 1

    session.commit()
    return RequeueResult(examined=len(rows), requeued=requeued)
