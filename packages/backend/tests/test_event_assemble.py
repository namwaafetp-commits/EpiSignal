from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from episignal_backend.ai.documents import AiRequestRecord
from episignal_backend.db.types import (
    CredibilityTier,
    LocationRole,
    Precision,
    RelationshipType,
    VerificationStatus,
)
from episignal_backend.events.assemble import AssemblySummary, run_event_assembly
from episignal_backend.events.documents import (
    CandidateEvent,
    LocationForMatching,
    SignalForMatching,
    StoryCluster,
)


class FakeAssemblyRepository:
    def __init__(
        self,
        signals: list[SignalForMatching] | None = None,
        candidates_by_disease: dict[UUID, list[CandidateEvent]] | None = None,
    ) -> None:
        self._signals = list(signals or [])
        self._candidates = candidates_by_disease or {}
        self.created_events: list[CandidateEvent] = []
        self.attached_signals: list[tuple[UUID, UUID, RelationshipType, float, bool]] = []
        self.recorded_observations: list[tuple[UUID, UUID]] = []
        self.added_locations: list[tuple[UUID, LocationForMatching]] = []
        self.applied_scores: dict[UUID, tuple[float, float, VerificationStatus]] = {}
        self.matched_signal_ids: set[UUID] = set()
        self.ai_requests: list[AiRequestRecord] = []
        self.committed = False
        self.rolled_back = False

    def signals_to_match(self, limit: int, *, stale: bool = False) -> list[SignalForMatching]:
        return self._signals[:limit]

    def candidate_events(
        self,
        cluster: StoryCluster,
        *,
        lookback_days: int = 7,
        limit: int = 20,
        distance_km: float = 50.0,
    ) -> list[CandidateEvent]:
        assert cluster.disease_id is not None
        return self._candidates.get(cluster.disease_id, [])

    def recent_source_titles(self, event_id: UUID, *, limit: int = 5) -> tuple[str, ...]:
        return ()

    def create_event(self, cluster: StoryCluster) -> CandidateEvent:
        rep_loc = cluster.representative_location
        locs = (rep_loc,) if rep_loc is not None else ()
        cand = CandidateEvent(
            event_id=uuid4(),
            disease_id=cluster.disease_id,
            locations=locs,
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
        self.matched_signal_ids.add(signal_id)

    def latest_brief(self, event_id: UUID) -> None:
        del event_id
        return None

    def record_ai_request(self, record: AiRequestRecord) -> None:
        self.ai_requests.append(record)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def _make_signal(
    *,
    disease_id: UUID | None,
    loc: LocationForMatching | None = None,
    published_at: datetime,
    is_official: bool = True,
    cred_tier: CredibilityTier = CredibilityTier.OFFICIAL,
    embedding: tuple[float, ...] | None = None,
) -> SignalForMatching:
    locations = (loc,) if loc is not None else ()
    return SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=is_official,
        credibility_tier=cred_tier,
        published_at=published_at,
        first_seen_at=published_at,
        locations=locations,
        embedding=embedding,
    )


def test_empty_input_returns_zero_counts() -> None:
    repo = FakeAssemblyRepository([])
    summary = run_event_assembly(repo)

    assert isinstance(summary, AssemblySummary)
    assert summary.signals_seen == 0
    assert summary.clusters_built == 0
    assert summary.events_created == 0
    assert repo.committed is True


def test_unclusterable_signal_creates_an_unknown_disease_event() -> None:
    now = datetime.now(UTC)
    # Signal with no disease cannot be clustered, but the Lean MVP still
    # preserves it as an event instead of opening a human-review case.
    sig_no_disease = _make_signal(disease_id=None, published_at=now)

    repo = FakeAssemblyRepository([sig_no_disease])
    summary = run_event_assembly(repo)

    assert summary.signals_seen == 1
    assert summary.unclusterable == 1
    assert summary.events_created == 1
    assert repo.created_events[0].disease_id is None
    assert repo.committed is True


def test_clear_new_cluster_creates_event_and_attaches_signals() -> None:
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        admin2="Beni",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )
    sig1 = _make_signal(disease_id=disease_id, loc=loc, published_at=now)
    sig2 = _make_signal(disease_id=disease_id, loc=loc, published_at=now + timedelta(hours=2))

    repo = FakeAssemblyRepository([sig1, sig2])
    summary = run_event_assembly(repo)

    assert summary.signals_seen == 2
    assert summary.clusters_built == 1
    assert summary.events_created == 1
    assert summary.signals_attached == 2
    assert len(repo.created_events) == 1
    created_id = repo.created_events[0].event_id

    # Check attached signals: first is primary, second is supporting
    assert len(repo.attached_signals) == 2
    ev_id_0, sig_id_0, rel_0, score_0, is_prim_0 = repo.attached_signals[0]
    assert ev_id_0 == created_id
    assert sig_id_0 == sig1.signal_id
    assert is_prim_0 is True
    assert rel_0 == RelationshipType.INITIAL_REPORT

    ev_id_1, sig_id_1, rel_1, score_1, is_prim_1 = repo.attached_signals[1]
    assert ev_id_1 == created_id
    assert sig_id_1 == sig2.signal_id
    assert is_prim_1 is False
    assert rel_1 == RelationshipType.SUPPORTING_SOURCE

    # Scores applied
    assert created_id in repo.applied_scores
    assert repo.committed is True


def test_attach_decision_updates_existing_event_and_recomputes_scores() -> None:
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        admin2="Beni",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )
    existing_ev_id = uuid4()
    existing_cand = CandidateEvent(
        event_id=existing_ev_id,
        disease_id=disease_id,
        locations=(loc,),
        first_signal_at=now - timedelta(days=5),
        last_updated_at=now - timedelta(days=1),
    )

    sig_new = _make_signal(disease_id=disease_id, loc=loc, published_at=now)

    repo = FakeAssemblyRepository([sig_new], candidates_by_disease={disease_id: [existing_cand]})
    summary = run_event_assembly(repo)

    assert summary.signals_seen == 1
    assert summary.events_created == 0
    assert summary.signals_attached == 1
    assert len(repo.attached_signals) == 1
    ev_id, sig_id, rel, score, is_prim = repo.attached_signals[0]
    assert ev_id == existing_ev_id
    assert sig_id == sig_new.signal_id
    assert is_prim is False
    assert existing_ev_id in repo.applied_scores
    assert repo.committed is True


def test_refusal_creates_a_new_event_without_human_review() -> None:
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        admin2="Beni",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )
    # 2 competing candidates at exact same location and disease
    cand_1 = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(loc,),
        first_signal_at=now - timedelta(days=2),
        last_updated_at=now - timedelta(days=1),
    )
    cand_2 = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(loc,),
        first_signal_at=now - timedelta(days=3),
        last_updated_at=now - timedelta(days=1),
    )

    sig = _make_signal(disease_id=disease_id, loc=loc, published_at=now)

    repo = FakeAssemblyRepository([sig], candidates_by_disease={disease_id: [cand_1, cand_2]})
    summary = run_event_assembly(repo)

    assert summary.signals_seen == 1
    assert summary.signals_refused == 0
    assert summary.events_created == 1
    assert summary.signals_attached == 1
    assert repo.created_events
    assert repo.committed is True
