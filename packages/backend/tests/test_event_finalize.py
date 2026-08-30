"""Tests for shared event finalization helper functions."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from episignal_backend.ai.schema import BriefPoint
from episignal_backend.db.types import (
    CredibilityTier,
    LocationRole,
    Precision,
    RelationshipType,
    VerificationStatus,
)
from episignal_backend.events.documents import (
    CandidateEvent,
    LocationForMatching,
    SignalForMatching,
    StoryCluster,
)
from episignal_backend.events.finalize import (
    finalize_event_creation,
    finalize_event_link,
)


class FakeEventRepository:
    def __init__(self) -> None:
        self.created_events: list[CandidateEvent] = []
        self.attached_signals: list[tuple[UUID, UUID, RelationshipType, float, bool]] = []
        self.recorded_observations: list[tuple[UUID, UUID]] = []
        self.added_locations: list[tuple[UUID, LocationForMatching]] = []
        self.applied_scores: dict[UUID, tuple[float, float, VerificationStatus]] = {}
        self.matched_signals: set[UUID] = set()
        self.latest_briefs: dict[UUID, tuple[BriefPoint, ...]] = {}

    def create_event(self, cluster: StoryCluster) -> CandidateEvent:
        cand = CandidateEvent(
            event_id=uuid4(),
            disease_id=cluster.disease_id,
            locations=cluster.representative_location and (cluster.representative_location,) or (),
            first_signal_at=cluster.span[0],
            last_updated_at=cluster.span[1],
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

    def add_locations(self, event_id: UUID, locations: list[LocationForMatching]) -> None:
        for loc in locations:
            self.added_locations.append((event_id, loc))

    def apply_scores(
        self,
        event_id: UUID,
        early_signal_score: float,
        evidence_score: float,
        verification_status: VerificationStatus,
    ) -> None:
        self.applied_scores[event_id] = (
            early_signal_score,
            evidence_score,
            verification_status,
        )

    def mark_matched(self, signal_id: UUID) -> None:
        self.matched_signals.add(signal_id)

    def latest_brief(self, event_id: UUID) -> tuple[BriefPoint, ...] | None:
        return self.latest_briefs.get(event_id)

    def apply_delta(self, event_id: UUID, signal_id: UUID, delta: dict) -> None:
        pass

    def record_ai_request(self, record: Any) -> None:
        pass


def test_finalize_event_link_attaches_observation_and_recomputes_scores() -> None:
    repo = FakeEventRepository()
    event_id = uuid4()
    disease_id = uuid4()
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="YE",
        latitude=15.37,
        longitude=44.19,
    )
    sig = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=True,
        locations=(loc,),
        published_at=now,
        first_seen_at=now,
        credibility_tier=CredibilityTier.OFFICIAL,
        extraction=None,
    )

    finalize_event_link(
        repo,  # type: ignore[arg-type]
        event_id=event_id,
        signal=sig,
        relationship_type=RelationshipType.SUPPORTING_SOURCE,
        match_score=0.92,
        is_primary=False,
        now=lambda: now,
    )

    assert len(repo.attached_signals) == 1
    assert repo.attached_signals[0] == (
        event_id,
        sig.signal_id,
        RelationshipType.SUPPORTING_SOURCE,
        0.92,
        False,
    )
    assert len(repo.recorded_observations) == 1
    assert repo.recorded_observations[0] == (event_id, sig.signal_id)
    assert len(repo.added_locations) == 1
    assert sig.signal_id in repo.matched_signals
    assert event_id in repo.applied_scores


def test_finalize_event_creation_creates_event_and_attaches_all_cluster_signals() -> None:
    repo = FakeEventRepository()
    disease_id = uuid4()
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="YE",
        latitude=15.37,
        longitude=44.19,
    )
    sig1 = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=True,
        locations=(loc,),
        published_at=now,
        first_seen_at=now,
        credibility_tier=CredibilityTier.OFFICIAL,
        extraction=None,
    )
    sig2 = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=False,
        locations=(loc,),
        published_at=now + timedelta(hours=1),
        first_seen_at=now + timedelta(hours=1),
        credibility_tier=CredibilityTier.MEDIUM,
        extraction=None,
    )
    cluster = StoryCluster(
        signals=(sig1, sig2),
    )

    created = finalize_event_creation(
        repo,  # type: ignore[arg-type]
        cluster=cluster,
        now=lambda: now,
    )

    assert len(repo.created_events) == 1
    assert created.event_id == repo.created_events[0].event_id
    assert len(repo.attached_signals) == 2
    # First is primary initial report
    assert repo.attached_signals[0] == (
        created.event_id,
        sig1.signal_id,
        RelationshipType.INITIAL_REPORT,
        1.0,
        True,
    )
    # Second is supporting
    assert repo.attached_signals[1] == (
        created.event_id,
        sig2.signal_id,
        RelationshipType.SUPPORTING_SOURCE,
        1.0,
        False,
    )
    assert len(repo.recorded_observations) == 2
    assert sig1.signal_id in repo.matched_signals
    assert sig2.signal_id in repo.matched_signals
    assert created.event_id in repo.applied_scores
