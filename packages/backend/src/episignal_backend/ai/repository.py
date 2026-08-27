"""The storage boundary for the AI passes.

Deliberately unable to discover, fetch, or deduplicate: this pass reads stored
signals, asks a model about them, and writes back what it learned. It is also
the only module in `ai/` that imports SQLAlchemy, and it owns transactions on
behalf of the passes above it.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from episignal_backend.ai.documents import (
    AiRequestRecord,
    ClassifiableSignal,
    ExtractableSignal,
    ModelSpec,
    StoredExtraction,
    Verdict,
)
from episignal_backend.db.types import ProcessingStatus
from episignal_backend.models import AiModel, AiRequest, Disease, Signal

EXCERPT_CHARACTERS = 1200


class SqlAlchemyAiRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def models(self) -> Sequence[ModelSpec]:
        rows = self._session.execute(
            select(AiModel).where(AiModel.active.is_(True)).order_by(AiModel.tier)
        ).scalars()
        return tuple(
            ModelSpec(
                id=row.id,
                tier=row.tier,
                model_id=row.model_id,
                label=row.label,
                prompt_price_per_million=row.prompt_price_per_million,
                completion_price_per_million=row.completion_price_per_million,
            )
            for row in rows
        )

    def awaiting_classification(self, *, limit: int) -> Sequence[ClassifiableSignal]:
        # The enforcement of the first invariant: `duplicate`, `needs_review`,
        # and `fetched` are simply not selectable here, so no later change can
        # send one to a model by accident.
        rows = self._session.execute(
            select(Signal)
            .where(
                Signal.processing_status == ProcessingStatus.NORMALIZED,
                Signal.raw_text.is_not(None),
            )
            .order_by(Signal.first_seen_at)
            .limit(limit)
        ).scalars()
        return tuple(
            ClassifiableSignal(
                id=row.id,
                title=row.title,
                excerpt=(row.raw_text or "")[:EXCERPT_CHARACTERS],
            )
            for row in rows
        )

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        rows = self._session.execute(
            select(Signal)
            .where(
                Signal.processing_status == ProcessingStatus.CLASSIFIED,
                Signal.public_health_relevant.is_(True),
                Signal.raw_text.is_not(None),
            )
            .order_by(Signal.first_seen_at)
            .limit(limit)
        ).scalars()
        return tuple(
            ExtractableSignal(id=row.id, title=row.title, raw_text=row.raw_text or "")
            for row in rows
        )

    def resolve_disease(self, name: str) -> UUID | None:
        # Case-folded exact match against the reviewed vocabulary, including
        # synonyms. No fuzzy matching: guessing which disease was meant is how a
        # measles report becomes a cholera event.
        needle = " ".join(name.split()).lower()
        return self._session.execute(
            select(Disease.id).where(
                or_(
                    func.lower(Disease.canonical_name) == needle,
                    func.lower(Disease.slug) == needle,
                    Disease.synonyms.any(needle),  # type: ignore[arg-type]
                )
            )
        ).scalar_one_or_none()

    def record_request(self, record: AiRequestRecord) -> None:
        self._session.add(
            AiRequest(
                ai_model_id=record.ai_model_id,
                model_id=record.model_id,
                tier=record.tier,
                purpose=record.purpose,
                signal_id=record.signal_id,
                batch_size=record.batch_size,
                prompt_tokens=record.prompt_tokens,
                completion_tokens=record.completion_tokens,
                latency_ms=record.latency_ms,
                http_status=record.http_status,
                outcome=record.outcome,
                rejection_reason=record.rejection_reason,
                prompt_price_per_million=record.prompt_price_per_million,
                completion_price_per_million=record.completion_price_per_million,
                cost_usd=record.cost_usd,
                requested_at=record.requested_at,
            )
        )

    def record_classification(self, signal_id: UUID, verdict: Verdict) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(
                processing_status=ProcessingStatus.CLASSIFIED,
                public_health_relevant=verdict.is_public_health_relevant,
                relevance_score=verdict.relevance,
                signal_type=verdict.signal_type,
                ai_model=verdict.model_id,
                ai_processed_at=verdict.decided_at,
            )
        )

    def record_extraction(self, signal_id: UUID, stored: StoredExtraction) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(
                processing_status=ProcessingStatus.EXTRACTED,
                ai_extraction=stored.extraction.model_dump(mode="json"),
                ai_model=stored.model_id,
                ai_processed_at=stored.processed_at,
                disease_id=stored.disease_id,
                signal_type=stored.extraction.signal_type,
                summary=stored.extraction.summary,
            )
        )

    def mark_needs_review(self, signal_id: UUID) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(processing_status=ProcessingStatus.NEEDS_REVIEW)
        )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
