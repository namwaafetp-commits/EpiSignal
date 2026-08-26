"""SQLAlchemy implementation of the storage boundary.

Kept deliberately thin: it translates a `NormalizedSignal` into a `Signal` row
and answers existence questions. All ingestion decisions live in `pipeline.py`,
which never imports this module.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from episignal_backend.ingestion.documents import NormalizedSignal
from episignal_backend.models import Signal, Source


def build_signal(signal: NormalizedSignal, source_id: UUID) -> Signal:
    return Signal(
        source_id=source_id,
        external_id=signal.external_id,
        url=signal.url,
        canonical_url=signal.canonical_url,
        title=signal.title,
        raw_text=signal.raw_text,
        published_at=signal.published_at,
        retrieved_at=signal.retrieved_at,
        language=signal.language,
        content_hash=signal.content_hash,
        signal_type=signal.signal_type,
        processing_status=signal.processing_status,
    )


class SqlAlchemySignalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def source_id(self, name: str) -> UUID | None:
        return self._session.execute(
            select(Source.id).where(Source.name == name)
        ).scalar_one_or_none()

    def latest_published_at(self, source_id: UUID) -> datetime | None:
        return self._session.execute(
            select(func.max(Signal.published_at)).where(Signal.source_id == source_id)
        ).scalar_one_or_none()

    def exists(self, url: str, content_hash: str) -> bool:
        found = self._session.execute(
            select(Signal.id).where(Signal.url == url, Signal.content_hash == content_hash).limit(1)
        ).first()
        return found is not None

    def add(self, signal: NormalizedSignal, source_id: UUID) -> None:
        self._session.add(build_signal(signal, source_id))
        self._session.flush()

    def activate(self, source_id: UUID) -> None:
        self._session.execute(update(Source).where(Source.id == source_id).values(active=True))

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
