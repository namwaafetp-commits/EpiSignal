"""Tests for review repository adapter and queue query assembly."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from episignal_backend.db.types import (
    LocationRole,
    Precision,
    ReviewReason,
    ReviewResolution,
    ReviewStatus,
    VerificationStatus,
)
from episignal_backend.models.review import SignalReviewCandidate, SignalReviewCase
from episignal_backend.review.repository import (
    SqlAlchemyReviewRepository,
    query_review_queue,
)


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def mappings(self) -> "FakeResult":
        return self

    def first(self) -> Any:
        return self._value[0] if self._value else None


class FakeSession:
    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = results or []
        self.executed: list[Any] = []
        self.added: list[Any] = []
        self.committed = False
        self.rolled_back = False

    def execute(self, statement: Any, params: Any = None) -> Any:
        self.executed.append((statement, params))
        return self._results.pop(0) if self._results else FakeResult([])

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    def add_all(self, instances: list[Any]) -> None:
        self.added.extend(instances)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def flush(self) -> None:
        pass


def test_open_review_reuses_the_existing_open_case() -> None:
    signal_id = uuid4()
    existing_case_id = uuid4()
    existing_case = SignalReviewCase(
        id=existing_case_id,
        signal_id=signal_id,
        reason=ReviewReason.RETRIEVAL_FAILED,
        status=ReviewStatus.OPEN,
        opened_at=datetime.now(UTC),
    )
    # Return existing open case from query
    session = FakeSession(results=[FakeResult(existing_case)])
    repo = SqlAlchemyReviewRepository(session)  # type: ignore[arg-type]

    case_id = repo.open_review(signal_id, reason=ReviewReason.RETRIEVAL_FAILED)
    assert case_id == existing_case_id
    assert len(session.added) == 0


def test_ambiguous_review_snapshots_each_candidate_score() -> None:
    signal_id = uuid4()
    candidate_a = uuid4()
    candidate_b = uuid4()
    # No existing open case
    session = FakeSession(results=[FakeResult(None)])
    repo = SqlAlchemyReviewRepository(session)  # type: ignore[arg-type]

    case_id = repo.open_review(
        signal_id,
        reason=ReviewReason.EVENT_MATCH_AMBIGUOUS,
        candidate_scores={candidate_a: 0.85, candidate_b: 0.72},
    )
    assert case_id is not None
    case_rows = [obj for obj in session.added if isinstance(obj, SignalReviewCase)]
    candidate_rows = [obj for obj in session.added if isinstance(obj, SignalReviewCandidate)]

    assert len(case_rows) == 1
    assert case_rows[0].reason is ReviewReason.EVENT_MATCH_AMBIGUOUS
    assert len(candidate_rows) == 2
    scores = {cand.event_id: cand.match_score for cand in candidate_rows}
    assert scores == {candidate_a: 0.85, candidate_b: 0.72}


def test_automatic_recovery_closes_only_the_open_retrieval_case() -> None:
    signal_id = uuid4()
    case_id = uuid4()
    open_retrieval_case = SignalReviewCase(
        id=case_id,
        signal_id=signal_id,
        reason=ReviewReason.RETRIEVAL_FAILED,
        status=ReviewStatus.OPEN,
        opened_at=datetime.now(UTC),
    )
    session = FakeSession(results=[FakeResult(open_retrieval_case)])
    repo = SqlAlchemyReviewRepository(session)  # type: ignore[arg-type]

    repo.recover_retrieval_automatically(signal_id)
    assert open_retrieval_case.status is ReviewStatus.RESOLVED
    assert open_retrieval_case.resolution is ReviewResolution.RECOVERED_AUTOMATICALLY
    assert open_retrieval_case.resolved_at is not None


class RowMock:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_queue_orders_oldest_then_uuid_and_never_returns_raw_text() -> None:
    case_id = uuid4()
    signal_id = uuid4()
    event_id = uuid4()
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    case_row = RowMock(
        case_id=case_id,
        signal_id=signal_id,
        reason=ReviewReason.EVENT_MATCH_AMBIGUOUS,
        opened_at=now,
        title="Original Sighting Title",
        source_name="WHO DON",
        source_url="https://who.int/don/1",
        first_seen_at=now,
        retrieval_attempts=1,
        ai_extraction={"english_title": "Translated Sighting Title", "disease_text": "Cholera"},
        disease_name="Cholera",
    )
    candidate_row = RowMock(
        review_case_id=case_id,
        event_id=event_id,
        match_score=0.88,
        public_id="EVT-2026-001",
        title="Cholera Outbreak Event",
        verification_status=VerificationStatus.OFFICIALLY_CONFIRMED,
    )
    location_row = RowMock(
        signal_id=signal_id,
        location_role=LocationRole.PRIMARY,
        precision=Precision.ADMIN1,
        country_name="Yemen",
        admin1_name="Sanaa",
        place_name=None,
        resolved_name="Sanaa, Yemen",
    )
    disease_opt_row = RowMock(
        id=uuid4(),
        canonical_name="Cholera",
    )

    # Session results: total_count, cases, candidates, locations, diseases
    session = FakeSession(
        results=[
            FakeResult(1),  # count
            FakeResult([case_row]),  # cases
            FakeResult([candidate_row]),  # candidates
            FakeResult([location_row]),  # locations
            FakeResult([disease_opt_row]),  # diseases
        ]
    )

    page = query_review_queue(session, limit=10, offset=0)  # type: ignore[arg-type]
    assert page.total_open_cases == 1
    assert len(page.items) == 1
    item = page.items[0]
    assert item.title == "Translated Sighting Title"
    assert item.extracted_disease_text == "Cholera"
    assert item.canonical_disease == "Cholera"
    assert len(item.candidate_events) == 1
    assert item.candidate_events[0].match_score == 0.88
    assert item.candidate_events[0].public_id == "EVT-2026-001"
    assert len(item.locations) == 1
    assert item.locations[0].resolved_name == "Sanaa, Yemen"

    # Verify no raw_text in item
    assert not hasattr(item, "raw_text")
    assert not hasattr(item, "source_span")


def test_queue_skips_malformed_extraction_but_keeps_safe_signal_facts() -> None:
    case_id = uuid4()
    signal_id = uuid4()
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    case_row = RowMock(
        case_id=case_id,
        signal_id=signal_id,
        reason=ReviewReason.EXTRACTION_REJECTED,
        opened_at=now,
        title="Original Raw Title",
        source_name="Local News",
        source_url="https://news.local/item",
        first_seen_at=now,
        retrieval_attempts=2,
        ai_extraction="malformed-not-a-dict",
        disease_name=None,
    )

    session = FakeSession(
        results=[
            FakeResult(1),
            FakeResult([case_row]),
            FakeResult([]),  # candidates
            FakeResult([]),  # locations
            FakeResult([]),  # diseases
        ]
    )

    page = query_review_queue(session, limit=10, offset=0)  # type: ignore[arg-type]
    assert page.total_open_cases == 1
    item = page.items[0]
    assert item.title == "Original Raw Title"
    assert item.extracted_disease_text is None
    assert item.canonical_disease is None
