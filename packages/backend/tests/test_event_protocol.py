from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from episignal_backend.ai.documents import AiRequestRecord
from episignal_backend.ai.schema import BriefPoint
from episignal_backend.db.types import (
    RelationshipType,
    ReviewReason,
    VerificationStatus,
)
from episignal_backend.events.documents import (
    CandidateEvent,
    EventForSummary,
    LocationForMatching,
    SignalForMatching,
    StoryCluster,
)
from episignal_backend.events.protocol import EventRepository


class InMemoryEventRepository:
    """An in-memory fake satisfying the EventRepository protocol."""

    def __init__(self) -> None:
        self.created_events: list[CandidateEvent] = []
        self.attached_signals: list[tuple[UUID, UUID, RelationshipType, float, bool]] = []
        self.recorded_observations: list[tuple[UUID, UUID]] = []
        self.added_locations: list[tuple[UUID, LocationForMatching]] = []
        self.scores: dict[UUID, tuple[float, float, VerificationStatus]] = {}
        self.matched_signal_ids: set[UUID] = set()
        self.review_calls: list[tuple[UUID, ReviewReason, dict[UUID, float]]] = []
        self.committed = False
        self.rolled_back = False

    @property
    def needs_review_signal_ids(self) -> set[UUID]:
        return {call[0] for call in self.review_calls}

    def signals_to_match(self, limit: int, *, stale: bool = False) -> Sequence[SignalForMatching]:
        return ()

    def candidate_events(
        self,
        cluster: StoryCluster,
        *,
        lookback_days: int = 7,
        limit: int = 20,
        distance_km: float = 50.0,
    ) -> Sequence[CandidateEvent]:
        return ()

    def create_event(self, cluster: StoryCluster) -> CandidateEvent:
        now = datetime.now(UTC)
        assert cluster.disease_id is not None
        rep_loc = cluster.representative_location
        locations = (rep_loc,) if rep_loc is not None else ()
        cand = CandidateEvent(
            event_id=uuid4(),
            disease_id=cluster.disease_id,
            locations=locations,
            first_signal_at=cluster.span[0],
            last_updated_at=now,
        )
        self.created_events.append(cand)
        return cand

    def attach_signal(
        self,
        event_id: UUID,
        signal_id: UUID,
        *,
        relationship_type: RelationshipType,
        match_score: float,
        is_primary: bool,
    ) -> None:
        self.attached_signals.append(
            (event_id, signal_id, relationship_type, match_score, is_primary)
        )

    def record_observation(self, event_id: UUID, signal: SignalForMatching) -> None:
        self.recorded_observations.append((event_id, signal.signal_id))

    def add_locations(self, event_id: UUID, locations: Sequence[LocationForMatching]) -> None:
        for loc in locations:
            self.added_locations.append((event_id, loc))

    def apply_scores(
        self,
        event_id: UUID,
        early_signal_score: float,
        evidence_score: float,
        verification_status: VerificationStatus,
    ) -> None:
        self.scores[event_id] = (
            early_signal_score,
            evidence_score,
            verification_status,
        )

    def mark_matched(self, signal_id: UUID) -> None:
        self.matched_signal_ids.add(signal_id)

    def open_review(
        self,
        signal_id: UUID,
        *,
        reason: ReviewReason,
        candidate_scores: Mapping[UUID, float] | None = None,
    ) -> None:
        self.review_calls.append((signal_id, reason, dict(candidate_scores or {})))

    def latest_brief(self, event_id: UUID) -> tuple[BriefPoint, ...] | None:
        return None

    def apply_delta(self, event_id: UUID, signal_id: UUID, delta: dict) -> None:
        return None

    def record_ai_request(self, record: AiRequestRecord) -> None:
        return None

    def events_awaiting_summary(
        self, *, limit: int, max_age_hours: int
    ) -> Sequence[EventForSummary]:
        return ()

    def store_summary(
        self,
        *,
        event_id: UUID,
        headline: str,
        summary: str,
        trajectory: str,
        snapshot: Sequence[str],
        key_driver: str,
        response: str,
        risk: str,
        model_id: str,
        source_signal_ids: list[UUID],
        counts: dict[str, object] | None,
        now: datetime | None = None,
    ) -> int:
        return 1

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def test_event_repository_protocol_is_satisfiable_in_memory() -> None:
    repo = InMemoryEventRepository()
    assert isinstance(repo, EventRepository)
