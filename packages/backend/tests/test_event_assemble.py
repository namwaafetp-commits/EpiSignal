from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from episignal_backend.ai.documents import AiRequestRecord, ModelSpec
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.ai.schema import BriefPoint, BriefSlot, Extraction
from episignal_backend.db.types import (
    AiPurpose,
    CredibilityTier,
    LocationRole,
    Precision,
    RelationshipType,
    ReviewReason,
    SignalType,
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
        self.review_calls: list[tuple[UUID, ReviewReason, dict[UUID, float]]] = []
        self.latest_briefs: dict[UUID, tuple[BriefPoint, ...]] = {}
        self.applied_deltas: list[tuple[UUID, UUID, dict]] = []
        self.ai_requests: list[AiRequestRecord] = []
        self.committed = False
        self.rolled_back = False

    @property
    def needs_review_signal_ids(self) -> set[UUID]:
        return {call[0] for call in self.review_calls}

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
        assert cluster.disease_id is not None
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

    def open_review(
        self,
        signal_id: UUID,
        *,
        reason: ReviewReason,
        candidate_scores: Mapping[UUID, float] | None = None,
    ) -> None:
        self.review_calls.append((signal_id, reason, dict(candidate_scores or {})))

    def latest_brief(self, event_id: UUID) -> tuple[BriefPoint, ...] | None:
        return self.latest_briefs.get(event_id)

    def apply_delta(self, event_id: UUID, signal_id: UUID, delta: dict) -> None:
        self.applied_deltas.append((event_id, signal_id, delta))

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
    extraction: Extraction | None = None,
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
        extraction=extraction,
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


def test_unclusterable_signal_routes_to_needs_review() -> None:
    now = datetime.now(UTC)
    # Signal with no disease -> unclusterable
    sig_no_disease = _make_signal(disease_id=None, published_at=now)

    repo = FakeAssemblyRepository([sig_no_disease])
    summary = run_event_assembly(repo)

    assert summary.signals_seen == 1
    assert summary.unclusterable == 1
    assert sig_no_disease.signal_id in repo.needs_review_signal_ids
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


def test_similarity_is_wired_lazily_and_every_candidate_decision_is_logged(caplog) -> None:
    now = datetime.now(UTC)
    disease_id = uuid4()
    chiang_mai = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="TH",
        admin1="Chiang Mai",
        place_name="Chiang Mai",
        latitude=18.79,
        longitude=98.98,
    )
    chiang_mai_admin1 = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.ADMIN1,
        country_code="TH",
        admin1="Chiang Mai",
        latitude=18.79,
        longitude=98.98,
    )
    phuket_admin1 = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.ADMIN1,
        country_code="TH",
        admin1="Phuket",
        latitude=7.88,
        longitude=98.39,
    )
    signal = _make_signal(
        disease_id=disease_id,
        loc=chiang_mai,
        published_at=now,
        embedding=(1.0, 0.0),
    )
    matching_event = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(chiang_mai_admin1,),
        first_signal_at=now - timedelta(days=2),
        last_updated_at=now - timedelta(days=1),
        representative_embedding=(1.0, 0.0),
    )
    conflicting_event = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(phuket_admin1,),
        first_signal_at=now - timedelta(days=2),
        last_updated_at=now - timedelta(days=1),
        representative_embedding=(0.0, 1.0),
    )
    repository = FakeAssemblyRepository(
        [signal],
        candidates_by_disease={disease_id: [matching_event, conflicting_event]},
    )
    caplog.set_level("INFO")

    summary = run_event_assembly(repository, match_threshold=0.90)

    assert summary.events_created == 0
    assert repository.attached_signals[0][0] == matching_event.event_id
    assert "matched event" in caplog.text
    assert "similarity=1.0" in caplog.text
    assert "reason=conflicting_admin1" in caplog.text
    assert (
        f"event_id={conflicting_event.event_id} similarity=None score=0.0 reason=conflicting_admin1"
    ) in caplog.text


def test_refusal_routes_signals_to_needs_review() -> None:
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
    assert summary.signals_refused == 1
    assert summary.events_created == 0
    assert summary.signals_attached == 0
    assert sig.signal_id in repo.needs_review_signal_ids
    assert repo.committed is True


def _brief(counts_text: str = "No counts") -> tuple[BriefPoint, ...]:
    return (
        BriefPoint(slot=BriefSlot.WHAT_WHERE, text="Cholera in Sana'a", reported=True),
        BriefPoint(slot=BriefSlot.COUNTS, text=counts_text, reported=True),
        BriefPoint(slot=BriefSlot.TIMING, text="Reported this week", reported=True),
        BriefPoint(slot=BriefSlot.SPREAD, text="No spread reported", reported=False),
        BriefPoint(slot=BriefSlot.REPORTING, text="Ministry of Health", reported=True),
    )


def _extraction(counts_text: str = "No counts") -> Extraction:
    return Extraction(
        signal_type=SignalType.OUTBREAK_REPORT,
        title_english="Cholera in Sana'a",
        brief=_brief(counts_text),
        confidence=0.9,
    )


class FakeDeltaModel:
    def __init__(self, content: str | None = None, refuse: bool = False) -> None:
        self._content = content
        self._refuse = refuse
        self.calls = 0

    def complete(self, request) -> object:
        from episignal_backend.ai.documents import ChatResponse

        self.calls += 1
        if self._refuse:
            raise ModelUnavailable("refused")
        return ChatResponse(content=self._content or "{}", latency_ms=5)


_DELTA_JSON = """{
  "brief": [
    {"slot": "what_where", "text": "Cholera in Sana'a", "reported": true},
    {"slot": "counts", "text": "Cases rose to 400", "reported": true},
    {"slot": "timing", "text": "Reported this week", "reported": true},
    {"slot": "spread", "text": "No spread reported", "reported": false},
    {"slot": "reporting", "text": "Ministry of Health", "reported": true}
  ],
  "what_changed": "Case count updated from none reported to 400."
}"""


def _recent_candidate(disease_id: UUID, now: datetime, days: float) -> CandidateEvent:
    return CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(
            LocationForMatching(
                location_role=LocationRole.PRIMARY,
                precision=Precision.COUNTRY,
                country_code="YE",
                latitude=15.37,
                longitude=44.19,
            ),
        ),
        first_signal_at=now - timedelta(days=days + 1),
        last_updated_at=now - timedelta(days=days),
    )


def test_a_recent_attach_runs_the_delta_pass_and_costs_it() -> None:
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="YE",
        admin1="Sana'a",
        place_name="Sana'a",
        latitude=15.37,
        longitude=44.19,
    )
    sig = _make_signal(
        disease_id=disease_id,
        loc=loc,
        published_at=now,
        extraction=_extraction("Cases now 400"),
    )
    candidate = _recent_candidate(disease_id, now, days=2)
    repo = FakeAssemblyRepository([sig], {disease_id: [candidate]})
    repo.latest_briefs[candidate.event_id] = _brief("No counts")

    summary = run_event_assembly(
        repo,
        now=now,
        match_threshold=0.5,
        delta_model=FakeDeltaModel(_DELTA_JSON),
        delta_spec=_delta_spec(),
        followup_window_days=10.0,
    )

    assert summary.signals_attached == 1
    assert summary.deltas_applied == 1
    assert len(repo.applied_deltas) == 1
    event_id, signal_id, payload = repo.applied_deltas[0]
    assert event_id == candidate.event_id
    assert signal_id == sig.signal_id
    assert payload["what_changed"].startswith("Case count updated")
    assert len(repo.ai_requests) == 1
    assert repo.ai_requests[0].purpose is AiPurpose.FOLLOW_UP


def _delta_spec() -> ModelSpec:
    from decimal import Decimal

    return ModelSpec(
        id=uuid4(),
        tier=1,
        model_id="google/gemini-2.5-flash-lite",
        label="Gemini 2.5 Flash-Lite",
        provider="gemini",
        prompt_price_per_million=Decimal("0.10"),
        completion_price_per_million=Decimal("0.40"),
    )


def test_an_attach_older_than_the_window_skips_the_delta_pass() -> None:
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="YE",
        latitude=15.37,
        longitude=44.19,
    )
    sig = _make_signal(disease_id=disease_id, loc=loc, published_at=now, extraction=_extraction())
    candidate = _recent_candidate(disease_id, now, days=30)
    repo = FakeAssemblyRepository([sig], {disease_id: [candidate]})
    repo.latest_briefs[candidate.event_id] = _brief()

    summary = run_event_assembly(
        repo,
        now=now,
        match_threshold=0.5,
        delta_model=FakeDeltaModel(_DELTA_JSON),
        delta_spec=_delta_spec(),
        followup_window_days=10.0,
    )

    assert summary.signals_attached == 1
    assert summary.deltas_applied == 0
    assert repo.ai_requests == []


def test_an_attach_without_a_previous_brief_skips_the_delta_pass() -> None:
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="YE",
        latitude=15.37,
        longitude=44.19,
    )
    sig = _make_signal(disease_id=disease_id, loc=loc, published_at=now, extraction=_extraction())
    candidate = _recent_candidate(disease_id, now, days=2)
    repo = FakeAssemblyRepository([sig], {disease_id: [candidate]})

    summary = run_event_assembly(
        repo,
        now=now,
        match_threshold=0.5,
        delta_model=FakeDeltaModel(_DELTA_JSON),
        delta_spec=_delta_spec(),
        followup_window_days=10.0,
    )

    assert summary.signals_attached == 1
    assert summary.deltas_applied == 0


def test_a_failed_delta_pass_leaves_the_attach_standing() -> None:
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="YE",
        latitude=15.37,
        longitude=44.19,
    )
    sig = _make_signal(disease_id=disease_id, loc=loc, published_at=now, extraction=_extraction())
    candidate = _recent_candidate(disease_id, now, days=2)
    repo = FakeAssemblyRepository([sig], {disease_id: [candidate]})
    repo.latest_briefs[candidate.event_id] = _brief()

    summary = run_event_assembly(
        repo,
        now=now,
        match_threshold=0.5,
        delta_model=FakeDeltaModel(refuse=True),
        delta_spec=_delta_spec(),
        followup_window_days=10.0,
    )

    assert summary.signals_attached == 1
    assert summary.deltas_applied == 0
    assert repo.applied_deltas == []
    assert repo.matched_signal_ids == {sig.signal_id}


def test_a_new_event_is_never_a_delta() -> None:
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="YE",
        latitude=15.37,
        longitude=44.19,
    )
    sig = _make_signal(disease_id=disease_id, loc=loc, published_at=now, extraction=_extraction())
    repo = FakeAssemblyRepository([sig])

    summary = run_event_assembly(
        repo,
        now=now,
        match_threshold=0.5,
        delta_model=FakeDeltaModel(_DELTA_JSON),
        delta_spec=_delta_spec(),
        followup_window_days=10.0,
    )

    assert summary.events_created == 1
    assert summary.deltas_applied == 0
