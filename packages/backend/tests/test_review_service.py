"""Tests for transactional resolution of retry, disease, and dismissal review cases."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from episignal_backend.db.types import (
    ProcessingStatus,
    ReviewReason,
    ReviewResolution,
    ReviewStatus,
)
from episignal_backend.models import Disease, Signal
from episignal_backend.models.review import SignalReviewCase
from episignal_backend.review.documents import (
    AssignDiseaseCommand,
    DiseaseNotFound,
    DismissCommand,
    RetryExtractionCommand,
    RetryGeocodingCommand,
    RetryRetrievalCommand,
    ReviewActionNotAllowed,
    ReviewAlreadyResolved,
    ReviewCaseNotFound,
)
from episignal_backend.review.repository import SqlAlchemyReviewRepository


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> "FakeResult":
        return self

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value

    def all(self) -> Any:
        return self._value if isinstance(self._value, list) else [self._value]


class FakeSession:
    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = results or []
        self.executed: list[Any] = []
        self.added: list[Any] = []
        self.committed = False
        self.rolled_back = False

    def execute(self, statement: Any, params: Any = None) -> Any:
        self.executed.append((statement, params))
        return self._results.pop(0) if self._results else FakeResult(None)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def flush(self) -> None:
        pass


def test_retry_retrieval_resets_attempts_and_sets_status_fetched() -> None:
    case_id = uuid4()
    signal_id = uuid4()
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    case = SignalReviewCase(
        id=case_id,
        signal_id=signal_id,
        reason=ReviewReason.RETRIEVAL_FAILED,
        status=ReviewStatus.OPEN,
        opened_at=now,
    )
    signal = Signal(
        id=signal_id,
        source_id=uuid4(),
        url="https://news.example/1",
        title="Sample News",
        processing_status=ProcessingStatus.NEEDS_REVIEW,
        retrieval_attempts=3,
    )

    # Session results: 1) lock case query -> case, 2) lock signal query -> signal
    session = FakeSession(results=[FakeResult(case), FakeResult(signal)])
    repo = SqlAlchemyReviewRepository(session)  # type: ignore[arg-type]

    result = repo.resolve_review(
        case_id,
        RetryRetrievalCommand(
            case_id=case_id,
            reviewed_by="admin@episignal.org",
            action=ReviewResolution.RETRY_RETRIEVAL,
        ),
    )

    assert result.case_id == case_id
    assert result.resolution is ReviewResolution.RETRY_RETRIEVAL
    assert case.status is ReviewStatus.RESOLVED
    assert case.resolution is ReviewResolution.RETRY_RETRIEVAL
    assert signal.processing_status is ProcessingStatus.FETCHED
    assert signal.retrieval_attempts == 0
    assert session.committed is True


def test_retry_extraction_sets_status_classified_and_keeps_relevance_facts() -> None:
    case_id = uuid4()
    signal_id = uuid4()
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    case = SignalReviewCase(
        id=case_id,
        signal_id=signal_id,
        reason=ReviewReason.EXTRACTION_REJECTED,
        status=ReviewStatus.OPEN,
        opened_at=now,
    )
    signal = Signal(
        id=signal_id,
        source_id=uuid4(),
        url="https://news.example/1",
        title="Sample News",
        processing_status=ProcessingStatus.NEEDS_REVIEW,
        public_health_relevant=True,
        relevance_score=0.95,
    )

    session = FakeSession(results=[FakeResult(case), FakeResult(signal)])
    repo = SqlAlchemyReviewRepository(session)  # type: ignore[arg-type]

    result = repo.resolve_review(
        case_id,
        RetryExtractionCommand(
            case_id=case_id,
            reviewed_by="admin@episignal.org",
            action=ReviewResolution.RETRY_EXTRACTION,
        ),
    )

    assert result.case_id == case_id
    assert result.resolution is ReviewResolution.RETRY_EXTRACTION
    assert case.status is ReviewStatus.RESOLVED
    assert signal.processing_status is ProcessingStatus.CLASSIFIED
    assert signal.public_health_relevant is True
    assert signal.relevance_score == 0.95
    assert session.committed is True


def test_assign_disease_persists_disease_id_and_sets_status_extracted() -> None:
    case_id = uuid4()
    signal_id = uuid4()
    disease_id = uuid4()
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    case = SignalReviewCase(
        id=case_id,
        signal_id=signal_id,
        reason=ReviewReason.DISEASE_UNRESOLVED,
        status=ReviewStatus.OPEN,
        opened_at=now,
    )
    signal = Signal(
        id=signal_id,
        source_id=uuid4(),
        url="https://news.example/1",
        title="Sample News",
        processing_status=ProcessingStatus.NEEDS_REVIEW,
        disease_id=None,
    )
    disease = Disease(id=disease_id, canonical_name="Cholera")

    # Session: 1) lock case, 2) lock signal, 3) query disease
    session = FakeSession(results=[FakeResult(case), FakeResult(signal), FakeResult(disease)])
    repo = SqlAlchemyReviewRepository(session)  # type: ignore[arg-type]

    result = repo.resolve_review(
        case_id,
        AssignDiseaseCommand(
            case_id=case_id,
            reviewed_by="admin@episignal.org",
            action=ReviewResolution.ASSIGN_DISEASE,
            disease_id=disease_id,
        ),
    )

    assert result.case_id == case_id
    assert result.resolution is ReviewResolution.ASSIGN_DISEASE
    assert case.status is ReviewStatus.RESOLVED
    assert signal.processing_status is ProcessingStatus.EXTRACTED
    assert signal.disease_id == disease_id
    assert session.committed is True


def test_assign_disease_rejects_nonexistent_disease() -> None:
    case_id = uuid4()
    signal_id = uuid4()
    disease_id = uuid4()
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    case = SignalReviewCase(
        id=case_id,
        signal_id=signal_id,
        reason=ReviewReason.DISEASE_UNRESOLVED,
        status=ReviewStatus.OPEN,
        opened_at=now,
    )
    signal = Signal(
        id=signal_id,
        source_id=uuid4(),
        url="https://news.example/1",
        title="Sample News",
        processing_status=ProcessingStatus.NEEDS_REVIEW,
    )

    # Session: 1) lock case, 2) lock signal, 3) disease not found (None)
    session = FakeSession(results=[FakeResult(case), FakeResult(signal), FakeResult(None)])
    repo = SqlAlchemyReviewRepository(session)  # type: ignore[arg-type]

    with pytest.raises(DiseaseNotFound):
        repo.resolve_review(
            case_id,
            AssignDiseaseCommand(
                case_id=case_id,
                reviewed_by="admin@episignal.org",
                action=ReviewResolution.ASSIGN_DISEASE,
                disease_id=disease_id,
            ),
        )


def test_retry_geocoding_sets_status_extracted() -> None:
    case_id = uuid4()
    signal_id = uuid4()
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    case = SignalReviewCase(
        id=case_id,
        signal_id=signal_id,
        reason=ReviewReason.LOCATION_UNRESOLVED,
        status=ReviewStatus.OPEN,
        opened_at=now,
    )
    signal = Signal(
        id=signal_id,
        source_id=uuid4(),
        url="https://news.example/1",
        title="Sample News",
        processing_status=ProcessingStatus.NEEDS_REVIEW,
    )

    session = FakeSession(results=[FakeResult(case), FakeResult(signal)])
    repo = SqlAlchemyReviewRepository(session)  # type: ignore[arg-type]

    result = repo.resolve_review(
        case_id,
        RetryGeocodingCommand(
            case_id=case_id,
            reviewed_by="admin@episignal.org",
            action=ReviewResolution.RETRY_GEOCODING,
        ),
    )

    assert result.case_id == case_id
    assert result.resolution is ReviewResolution.RETRY_GEOCODING
    assert case.status is ReviewStatus.RESOLVED
    assert signal.processing_status is ProcessingStatus.EXTRACTED
    assert session.committed is True


def test_dismiss_sets_status_dismissed_and_resolves_case() -> None:
    case_id = uuid4()
    signal_id = uuid4()
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    case = SignalReviewCase(
        id=case_id,
        signal_id=signal_id,
        reason=ReviewReason.CONTENT_INTEGRITY,
        status=ReviewStatus.OPEN,
        opened_at=now,
    )
    signal = Signal(
        id=signal_id,
        source_id=uuid4(),
        url="https://news.example/1",
        title="Sample News",
        processing_status=ProcessingStatus.NEEDS_REVIEW,
    )

    session = FakeSession(results=[FakeResult(case), FakeResult(signal)])
    repo = SqlAlchemyReviewRepository(session)  # type: ignore[arg-type]

    result = repo.resolve_review(
        case_id,
        DismissCommand(
            case_id=case_id,
            reviewed_by="admin@episignal.org",
            action=ReviewResolution.DISMISS,
            note="Dismissing content integrity failure",
        ),
    )

    assert result.case_id == case_id
    assert result.resolution is ReviewResolution.DISMISS
    assert case.status is ReviewStatus.RESOLVED
    assert signal.processing_status is ProcessingStatus.DISMISSED
    assert session.committed is True


def test_resolving_already_resolved_case_raises_review_already_resolved() -> None:
    case_id = uuid4()
    signal_id = uuid4()
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    case = SignalReviewCase(
        id=case_id,
        signal_id=signal_id,
        reason=ReviewReason.RETRIEVAL_FAILED,
        status=ReviewStatus.RESOLVED,
        resolution=ReviewResolution.DISMISS,
        opened_at=now,
        resolved_at=now,
    )

    session = FakeSession(results=[FakeResult(case)])
    repo = SqlAlchemyReviewRepository(session)  # type: ignore[arg-type]

    with pytest.raises(ReviewAlreadyResolved):
        repo.resolve_review(
            case_id,
            DismissCommand(
                case_id=case_id,
                reviewed_by="admin@episignal.org",
                action=ReviewResolution.DISMISS,
                note="Already resolved",
            ),
        )


def test_incompatible_resolution_action_raises_review_action_not_allowed() -> None:
    case_id = uuid4()
    signal_id = uuid4()
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    case = SignalReviewCase(
        id=case_id,
        signal_id=signal_id,
        reason=ReviewReason.RETRIEVAL_FAILED,
        status=ReviewStatus.OPEN,
        opened_at=now,
    )
    signal = Signal(
        id=signal_id,
        source_id=uuid4(),
        url="https://news.example/1",
        title="Sample News",
        processing_status=ProcessingStatus.NEEDS_REVIEW,
    )

    # Attempting to assign disease to a retrieval_failed case
    session = FakeSession(results=[FakeResult(case), FakeResult(signal)])
    repo = SqlAlchemyReviewRepository(session)  # type: ignore[arg-type]

    with pytest.raises(ReviewActionNotAllowed):
        repo.resolve_review(
            case_id,
            AssignDiseaseCommand(
                case_id=case_id,
                reviewed_by="admin@episignal.org",
                action=ReviewResolution.ASSIGN_DISEASE,
                disease_id=uuid4(),
            ),
        )
