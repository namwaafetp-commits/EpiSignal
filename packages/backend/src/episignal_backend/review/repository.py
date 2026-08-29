"""SqlAlchemy adapter and queue assembly for manual review cases."""

from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from episignal_backend.db.types import (
    ProcessingStatus,
    ReviewReason,
    ReviewResolution,
    ReviewStatus,
)
from episignal_backend.models import (
    Disease,
    Event,
    Signal,
    SignalLocation,
    Source,
)
from episignal_backend.models.review import (
    SignalReviewCandidate,
    SignalReviewCase,
)
from episignal_backend.review.documents import (
    ALLOWED_RESOLUTIONS,
    AssignDiseaseCommand,
    CreateEventCommand,
    DiseaseNotFound,
    DismissCommand,
    LinkEventCommand,
    ResolveReviewCommand,
    RetryExtractionCommand,
    RetryGeocodingCommand,
    RetryRetrievalCommand,
    ReviewActionNotAllowed,
    ReviewAlreadyResolved,
    ReviewCandidateEvent,
    ReviewCaseNotFound,
    ReviewCaseResult,
    ReviewDiseaseOption,
    ReviewQueueItem,
    ReviewQueuePage,
    ReviewSignalLocation,
    ReviewTargetStale,
)
from episignal_backend.review.protocol import LockedReviewCase


class SqlAlchemyReviewRepository:
    """SQLAlchemy adapter for review case storage."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def open_review(
        self,
        signal_id: UUID,
        *,
        reason: ReviewReason,
        candidate_scores: Mapping[UUID, float] | None = None,
    ) -> UUID:
        """Open or reuse an existing open review case for a signal."""
        stmt = select(SignalReviewCase).where(
            SignalReviewCase.signal_id == signal_id,
            SignalReviewCase.status == ReviewStatus.OPEN,
        )
        existing = self._session.execute(stmt).scalar_one_or_none()
        if existing is not None:
            return existing.id

        case_id = uuid4()
        case = SignalReviewCase(
            id=case_id,
            signal_id=signal_id,
            reason=reason,
            status=ReviewStatus.OPEN,
            opened_at=datetime.now(UTC),
        )
        self._session.add(case)
        self._session.flush()

        if candidate_scores:
            for event_id, score in candidate_scores.items():
                cand = SignalReviewCandidate(
                    review_case_id=case.id,
                    event_id=event_id,
                    match_score=score,
                )
                self._session.add(cand)

        return case.id

    def lock_review_case(self, case_id: UUID) -> LockedReviewCase:
        """Lock and return the review case, underlying signal, and candidate snapshot."""
        stmt = (
            select(SignalReviewCase)
            .where(SignalReviewCase.id == case_id)
            .with_for_update()
        )
        case = self._session.execute(stmt).scalar_one_or_none()
        if case is None:
            raise ReviewCaseNotFound(case_id)
        if case.status is not ReviewStatus.OPEN:
            raise ReviewAlreadyResolved(case_id)

        sig_stmt = select(Signal).where(Signal.id == case.signal_id).with_for_update()
        signal = self._session.execute(sig_stmt).scalar_one_or_none()
        if signal is None:
            raise ReviewCaseNotFound(case_id)

        return LockedReviewCase(
            id=case.id,
            signal_id=case.signal_id,
            reason=case.reason,
            status=case.status,
        )

    def resolve_review(
        self, case_id: UUID, command: ResolveReviewCommand
    ) -> ReviewCaseResult:
        """Resolve a review case transactionally according to domain rules."""
        stmt = (
            select(SignalReviewCase)
            .where(SignalReviewCase.id == case_id)
            .with_for_update()
        )
        case = self._session.execute(stmt).scalar_one_or_none()
        if case is None:
            raise ReviewCaseNotFound(case_id)
        if case.status is not ReviewStatus.OPEN:
            raise ReviewAlreadyResolved(case_id)

        sig_stmt = select(Signal).where(Signal.id == case.signal_id).with_for_update()
        signal = self._session.execute(sig_stmt).scalar_one_or_none()
        if signal is None:
            raise ReviewCaseNotFound(case_id)

        allowed = ALLOWED_RESOLUTIONS.get(case.reason, frozenset())
        if command.action not in allowed:
            raise ReviewActionNotAllowed(case.reason, command.action)

        selected_disease_id: UUID | None = None
        selected_event_id: UUID | None = None

        if command.action is ReviewResolution.RETRY_RETRIEVAL:
            signal.retrieval_attempts = 0
            signal.processing_status = ProcessingStatus.FETCHED
        elif command.action is ReviewResolution.RETRY_EXTRACTION:
            signal.processing_status = ProcessingStatus.CLASSIFIED
        elif command.action is ReviewResolution.ASSIGN_DISEASE:
            assert isinstance(command, AssignDiseaseCommand)
            disease_stmt = select(Disease).where(Disease.id == command.disease_id)
            disease = self._session.execute(disease_stmt).scalar_one_or_none()
            if disease is None:
                raise DiseaseNotFound(command.disease_id)
            signal.disease_id = command.disease_id
            signal.processing_status = ProcessingStatus.EXTRACTED
            selected_disease_id = command.disease_id
        elif command.action is ReviewResolution.RETRY_GEOCODING:
            signal.processing_status = ProcessingStatus.EXTRACTED
        elif command.action is ReviewResolution.DISMISS:
            signal.processing_status = ProcessingStatus.DISMISSED
        elif command.action is ReviewResolution.LINK_EVENT:
            pass
        elif command.action is ReviewResolution.CREATE_EVENT:
            pass

        now = datetime.now(UTC)
        case.status = ReviewStatus.RESOLVED
        case.resolution = command.action
        case.reviewed_by = command.reviewed_by
        case.resolved_at = now
        self._session.commit()

        return ReviewCaseResult(
            case_id=case.id,
            signal_id=signal.id,
            resolution=command.action,
            processing_status=signal.processing_status,
            selected_disease_id=selected_disease_id,
            selected_event_id=selected_event_id,
            resolved_at=now,
        )

    def recover_retrieval_automatically(self, signal_id: UUID) -> None:
        """Close only the open retrieval_failed case when discovery succeeds."""
        stmt = (
            select(SignalReviewCase)
            .where(
                SignalReviewCase.signal_id == signal_id,
                SignalReviewCase.status == ReviewStatus.OPEN,
                SignalReviewCase.reason == ReviewReason.RETRIEVAL_FAILED,
            )
        )
        case = self._session.execute(stmt).scalar_one_or_none()
        if case is not None:
            case.status = ReviewStatus.RESOLVED
            case.resolution = ReviewResolution.RECOVERED_AUTOMATICALLY
            case.resolved_at = datetime.now(UTC)


def query_review_queue(
    session: Session, *, limit: int = 50, offset: int = 0
) -> ReviewQueuePage:
    """Query open review cases with safe facts and resolution metadata."""
    count_stmt = select(func.count(SignalReviewCase.id)).where(
        SignalReviewCase.status == ReviewStatus.OPEN
    )
    total_cases = session.execute(count_stmt).scalar_one()

    cases_stmt = (
        select(
            SignalReviewCase.id.label("case_id"),
            SignalReviewCase.signal_id.label("signal_id"),
            SignalReviewCase.reason.label("reason"),
            SignalReviewCase.opened_at.label("opened_at"),
            Signal.title.label("title"),
            Signal.first_seen_at.label("first_seen_at"),
            Signal.retrieval_attempts.label("retrieval_attempts"),
            Signal.ai_extraction.label("ai_extraction"),
            Source.name.label("source_name"),
            Source.base_url.label("source_url"),
            Disease.canonical_name.label("disease_name"),
        )
        .select_from(SignalReviewCase)
        .join(Signal, Signal.id == SignalReviewCase.signal_id)
        .join(Source, Source.id == Signal.source_id)
        .outerjoin(Disease, Disease.id == Signal.disease_id)
        .where(SignalReviewCase.status == ReviewStatus.OPEN)
        .order_by(SignalReviewCase.opened_at.asc(), SignalReviewCase.id.asc())
        .limit(limit)
        .offset(offset)
    )
    case_rows = session.execute(cases_stmt).all()

    case_ids = [row.case_id for row in case_rows]
    candidates_by_case: dict[UUID, list[ReviewCandidateEvent]] = defaultdict(list)
    if case_ids:
        cand_stmt = (
            select(
                SignalReviewCandidate.review_case_id,
                SignalReviewCandidate.event_id,
                SignalReviewCandidate.match_score,
                Event.public_id,
                Event.title,
                Event.verification_status,
            )
            .select_from(SignalReviewCandidate)
            .join(Event, Event.id == SignalReviewCandidate.event_id)
            .where(SignalReviewCandidate.review_case_id.in_(case_ids))
            .order_by(SignalReviewCandidate.match_score.desc())
        )
        for cand_row in session.execute(cand_stmt).all():
            candidates_by_case[cand_row.review_case_id].append(
                ReviewCandidateEvent(
                    event_id=cand_row.event_id,
                    public_id=cand_row.public_id,
                    title=cand_row.title,
                    verification_status=cand_row.verification_status,
                    match_score=cand_row.match_score,
                )
            )

    signal_ids = [row.signal_id for row in case_rows]
    locations_by_signal: dict[UUID, list[ReviewSignalLocation]] = defaultdict(list)
    if signal_ids:
        loc_stmt = (
            select(
                SignalLocation.signal_id,
                SignalLocation.location_role,
                SignalLocation.precision,
                SignalLocation.country_name,
                SignalLocation.admin1_name,
                SignalLocation.place_name,
                SignalLocation.resolved_name,
            )
            .where(SignalLocation.signal_id.in_(signal_ids))
            .order_by(SignalLocation.created_at.asc())
        )
        for loc_row in session.execute(loc_stmt).all():
            locations_by_signal[loc_row.signal_id].append(
                ReviewSignalLocation(
                    location_role=loc_row.location_role,
                    precision=loc_row.precision,
                    country_name=loc_row.country_name,
                    admin1_name=loc_row.admin1_name,
                    place_name=loc_row.place_name,
                    resolved_name=loc_row.resolved_name,
                )
            )

    disease_stmt = select(Disease.id, Disease.canonical_name).order_by(
        Disease.canonical_name.asc()
    )
    disease_options = [
        ReviewDiseaseOption(id=row.id, canonical_name=row.canonical_name)
        for row in session.execute(disease_stmt).all()
    ]

    items: list[ReviewQueueItem] = []
    for row in case_rows:
        title = row.title
        extracted_disease: str | None = None
        if isinstance(row.ai_extraction, dict):
            eng_title = row.ai_extraction.get("english_title")
            if isinstance(eng_title, str) and eng_title.strip():
                title = eng_title
            disease_val = row.ai_extraction.get("disease_text")
            if isinstance(disease_val, str) and disease_val.strip():
                extracted_disease = disease_val

        allowed = sorted(
            ALLOWED_RESOLUTIONS.get(row.reason, frozenset()),
            key=lambda a: a.value,
        )

        items.append(
            ReviewQueueItem(
                case_id=row.case_id,
                signal_id=row.signal_id,
                reason=row.reason,
                opened_at=row.opened_at,
                title=title,
                source_name=row.source_name,
                source_url=row.source_url,
                first_seen_at=row.first_seen_at,
                retrieval_attempts=row.retrieval_attempts,
                extracted_disease_text=extracted_disease,
                canonical_disease=row.disease_name,
                locations=locations_by_signal.get(row.signal_id, []),
                candidate_events=candidates_by_case.get(row.case_id, []),
                allowed_resolutions=allowed,
            )
        )

    return ReviewQueuePage(
        items=items,
        total_open_cases=total_cases,
        disease_options=disease_options,
        limit=limit,
        offset=offset,
    )
