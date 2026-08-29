"""The storage boundary for the AI passes.

Deliberately unable to discover, fetch, or deduplicate: this pass reads stored
signals, asks a model about them, and writes back what it learned. It is also
the only module in `ai/` that imports SQLAlchemy, and it owns transactions on
behalf of the passes above it.
"""

import logging
from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, or_, select, update
from sqlalchemy.orm import Session

from episignal_backend.ai.documents import (
    AiRequestRecord,
    ClassifiableSignal,
    ClusterMemberSignal,
    DiseaseCandidate,
    ExtractableCluster,
    ExtractableSignal,
    ModelSpec,
    StoredExtraction,
    Verdict,
)
from episignal_backend.ai.prompts import MAX_CLUSTER_MEMBERS
from episignal_backend.ai.schema import (
    BACKFILL_MIN_SCHEMA_VERSION,
    EXTRACTION_SCHEMA_VERSION,
    EXTRACTION_VERSION_KEY,
)
from episignal_backend.db.types import (
    ProcessingStatus,
    ReviewReason,
    StoryGroupRole,
    StoryGroupState,
)
from episignal_backend.ingestion.fingerprint import verify_content_hash
from episignal_backend.models import (
    AiModel,
    AiRequest,
    Disease,
    Signal,
    StoryGroup,
    StoryGroupMember,
)
from episignal_backend.review.repository import SqlAlchemyReviewRepository

logger = logging.getLogger(__name__)

EXCERPT_CHARACTERS = 1200
# The candidate list rides in one classification prompt, so it is capped: a
# vocabulary too large for one request is also too large for one-shot choice.
MAX_DISEASE_CANDIDATES = 400


class SqlAlchemyAiRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _scan_valid_signals(
        self,
        base_stmt: Select[tuple[Signal]],
        limit: int,
        pass_name: str,
    ) -> list[Signal]:
        chunk_size = max(limit, 20)
        max_scan = max(limit * 5, 100)
        offset = 0
        valid_signals: list[Signal] = []

        while len(valid_signals) < limit and offset < max_scan:
            chunk_stmt = base_stmt.offset(offset).limit(chunk_size)
            chunk_rows = list(self._session.execute(chunk_stmt).scalars().all())
            if not chunk_rows:
                break
            offset += len(chunk_rows)
            for row in chunk_rows:
                if not verify_content_hash(row.title, row.raw_text, row.content_hash):
                    logger.warning(
                        "Signal %s failed content hash integrity check; omitted from %s pass",
                        row.id,
                        pass_name,
                    )
                    continue
                valid_signals.append(row)
                if len(valid_signals) == limit:
                    break
            if len(chunk_rows) < chunk_size:
                break

        return valid_signals

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
                provider=row.provider,
                prompt_price_per_million=row.prompt_price_per_million,
                completion_price_per_million=row.completion_price_per_million,
            )
            for row in rows
        )

    def awaiting_classification(self, *, limit: int) -> Sequence[ClassifiableSignal]:
        # Bypassed in Phase 2: relevance classification is skipped and representatives
        # of open groups are extracted directly.
        return ()

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        stmt = (
            select(Signal)
            .where(
                Signal.processing_status == ProcessingStatus.NORMALIZED,
                Signal.raw_text.is_not(None),
                # Pre-group deferral: a member waiting on its open group's
                # representative is not selectable.
                ~_deferred_by_open_group(),
            )
            .order_by(Signal.first_seen_at)
        )
        rows = self._scan_valid_signals(stmt, limit, "extraction")
        return tuple(
            ExtractableSignal(id=row.id, title=row.title, raw_text=row.raw_text or "")
            for row in rows
        )

    def awaiting_backfill(self, *, limit: int) -> Sequence[ExtractableSignal]:
        """Signals whose stored extraction predates the current schema.

        `needs_review` and `normalized` are not selectable here for the same
        reason they are not selectable for extraction: one is owed a human
        decision, and the other has not been classified yet.
        """
        stored_version = Signal.ai_extraction[EXTRACTION_VERSION_KEY].as_integer()
        stmt = (
            select(Signal)
            .where(
                Signal.processing_status.in_(
                    (
                        ProcessingStatus.EXTRACTED,
                        ProcessingStatus.GEOCODED,
                        ProcessingStatus.MATCHED,
                        ProcessingStatus.PUBLISHED,
                    )
                ),
                Signal.ai_extraction.is_not(None),
                Signal.raw_text.is_not(None),
                or_(stored_version.is_(None), stored_version < BACKFILL_MIN_SCHEMA_VERSION),
            )
            .order_by(Signal.first_seen_at)
        )
        rows = self._scan_valid_signals(stmt, limit, "backfill")
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

    def disease_candidates(self) -> tuple[DiseaseCandidate, ...]:
        # Ordered by canonical name so the prompt the classifier sees is stable
        # between runs; an order that drifted would make its answers
        # incomparable.
        rows = self._session.execute(
            select(Disease).order_by(Disease.canonical_name).limit(MAX_DISEASE_CANDIDATES)
        ).scalars()
        return tuple(
            DiseaseCandidate(
                slug=row.slug,
                canonical_name=row.canonical_name,
                synonyms=tuple(row.synonyms),
            )
            for row in rows
        )

    def resolve_disease_slug(self, slug: str) -> UUID | None:
        # The classifier's slug is re-resolved against the vocabulary rather
        # than trusted: the database, not the model, decides what exists.
        needle = " ".join(slug.split()).lower()
        return self._session.execute(
            select(Disease.id).where(func.lower(Disease.slug) == needle)
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
        # The version is stamped here and never by the model: a version a model
        # can choose is a version that lies the moment the model is confused.
        payload = stored.extraction.model_dump(mode="json")
        payload[EXTRACTION_VERSION_KEY] = EXTRACTION_SCHEMA_VERSION

        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(
                processing_status=ProcessingStatus.EXTRACTED,
                ai_extraction=payload,
                ai_model=stored.model_id,
                ai_processed_at=stored.processed_at,
                disease_id=stored.disease_id,
                signal_type=stored.extraction.signal_type,
                summary="\n".join(point.text for point in stored.extraction.brief),
            )
        )

    def open_review(
        self,
        signal_id: UUID,
        *,
        reason: ReviewReason,
        candidate_scores: Mapping[UUID, float] | None = None,
    ) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(processing_status=ProcessingStatus.NEEDS_REVIEW)
        )
        SqlAlchemyReviewRepository(self._session).open_review(
            signal_id, reason=reason, candidate_scores=candidate_scores
        )

    def awaiting_cluster_extraction(self, *, limit: int) -> Sequence[ExtractableCluster]:
        group_ids = list(
            self._session.execute(
                select(StoryGroup.id)
                .where(StoryGroup.state == StoryGroupState.OPEN)
                .order_by(StoryGroup.opened_at.asc())
                .limit(limit)
            )
            .scalars()
            .all()
        )

        clusters: list[ExtractableCluster] = []
        for group_id in group_ids:
            rows = self._session.execute(
                select(Signal, StoryGroupMember.role)
                .join(StoryGroupMember, Signal.id == StoryGroupMember.signal_id)
                .where(StoryGroupMember.group_id == group_id)
                .order_by(
                    # representative (role=representative) always goes first.
                    # StoryGroupRole is a StrEnum, and "representative" > "deferred" alphabetically.
                    # So sorting desc() ensures representative goes first.
                    StoryGroupMember.role.desc(),
                    Signal.retrieved_at.asc(),
                )
            ).all()

            # Filter valid signals and map to ClusterMemberSignal
            members: list[ClusterMemberSignal] = []
            representative_id = None
            for signal, role in rows:
                if role == StoryGroupRole.REPRESENTATIVE:
                    representative_id = signal.id

                if signal.raw_text is None:
                    continue

                if not verify_content_hash(signal.title, signal.raw_text, signal.content_hash):
                    logger.warning(
                        "Signal %s failed content hash integrity check; omitted from cluster",
                        signal.id,
                    )
                    continue

                members.append(
                    ClusterMemberSignal(
                        id=signal.id,
                        source_index=len(members),
                        title=signal.title,
                        raw_text=signal.raw_text,
                    )
                )

            # Cap the cluster size to MAX_CLUSTER_MEMBERS
            members = members[:MAX_CLUSTER_MEMBERS]

            if representative_id is not None and members and members[0].id == representative_id:
                clusters.append(
                    ExtractableCluster(
                        group_id=group_id,
                        representative_id=representative_id,
                        members=tuple(members),
                    )
                )

        return tuple(clusters)

    def record_cluster_extraction(
        self, *, representative_id: UUID, member_ids: Sequence[UUID], stored: StoredExtraction
    ) -> None:
        payload = stored.extraction.model_dump(mode="json")
        payload[EXTRACTION_VERSION_KEY] = EXTRACTION_SCHEMA_VERSION

        # Update the representative signal
        self._session.execute(
            update(Signal)
            .where(Signal.id == representative_id)
            .values(
                processing_status=ProcessingStatus.EXTRACTED,
                ai_extraction=payload,
                ai_model=stored.model_id,
                ai_processed_at=stored.processed_at,
                disease_id=stored.disease_id,
                signal_type=stored.extraction.signal_type,
                summary="\n".join(point.text for point in stored.extraction.brief),
            )
        )

        # Update the duplicates (members other than the representative)
        other_ids = [m_id for m_id in member_ids if m_id != representative_id]
        if other_ids:
            self._session.execute(
                update(Signal)
                .where(Signal.id.in_(other_ids))
                .values(
                    processing_status=ProcessingStatus.DUPLICATE,
                    duplicate_of_signal_id=representative_id,
                )
            )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()


def _deferred_by_open_group() -> ColumnElement[bool]:
    return (
        select(StoryGroupMember.signal_id)
        .join(StoryGroup, StoryGroupMember.group_id == StoryGroup.id)
        .where(
            StoryGroupMember.signal_id == Signal.id,
            StoryGroupMember.role == StoryGroupRole.DEFERRED,
            StoryGroup.state == StoryGroupState.OPEN,
        )
        .exists()
    )
