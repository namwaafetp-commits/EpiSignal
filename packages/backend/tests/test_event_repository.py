from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from episignal_backend.ai.schema import (
    EXTRACTION_SCHEMA_VERSION,
    EXTRACTION_VERSION_KEY,
)
from episignal_backend.db.types import (
    CredibilityTier,
    LocationRole,
    Precision,
    SignalType,
)
from episignal_backend.events.documents import LocationForMatching, SignalForMatching
from episignal_backend.events.protocol import EventRepository
from episignal_backend.events.repository import (
    SqlAlchemyEventRepository,
    read_stored_extraction,
)


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> Any:
        if self._value is None:
            return []
        return self._value if isinstance(self._value, list) else [self._value]

    def scalar_one_or_none(self) -> Any:
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value

    def scalar_one(self) -> Any:
        return self._value

    def first(self) -> Any:
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value


class FakeSession:
    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = results or []
        self.executed: list[Any] = []
        self.added: list[Any] = []

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return self._results.pop(0) if self._results else FakeResult(None)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class SummaryCandidateSession(FakeSession):
    """Model the joined rows produced by an event with several signals."""

    def __init__(self, event_a: Any, event_b: Any) -> None:
        super().__init__()
        self._joined_event_ids = [event_a] * 5 + [event_b] * 2

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        event_ids = self._joined_event_ids
        if statement._group_by_clauses:
            event_ids = list(dict.fromkeys(event_ids))
        limit = statement._limit_clause.value
        return FakeResult(event_ids[:limit])


class FakeSignal:
    def __init__(
        self,
        signal_id,
        disease_id,
        source_id,
        published_at,
        first_seen_at,
        is_official,
        credibility_tier,
        extraction=None,
        embedding=None,
    ) -> None:
        self.id = signal_id
        self.disease_id = disease_id
        self.source_id = source_id
        self.published_at = published_at
        self.first_seen_at = first_seen_at
        self.is_official = is_official
        self.credibility_tier = credibility_tier
        self.ai_extraction = extraction
        self.embedding = embedding
        self.title = f"Signal {signal_id}"


class FakeLocation:
    def __init__(
        self,
        signal_id,
        role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        admin2="Beni",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    ) -> None:
        self.signal_id = signal_id
        self.location_role = role
        self.precision = precision
        self.country_code = country_code
        self.admin1 = admin1
        self.admin2 = admin2
        self.place_name = place_name
        self.latitude = latitude
        self.longitude = longitude


def test_events_awaiting_summary_deduplicates_signal_join_before_limit() -> None:
    event_a = uuid4()
    event_b = uuid4()
    session = SummaryCandidateSession(event_a, event_b)
    repository = SqlAlchemyEventRepository(session)
    repository._build_event_for_summary = lambda event_id: event_id  # type: ignore[method-assign]

    candidates = repository.events_awaiting_summary(limit=2, max_age_hours=48)

    assert candidates == (event_a, event_b)
    assert len(candidates) == len(set(candidates))
    assert session.executed[0]._group_by_clauses


def test_it_satisfies_the_event_repository_boundary() -> None:
    repo = SqlAlchemyEventRepository(FakeSession())
    assert isinstance(repo, EventRepository)


def test_signals_to_match_uses_direct_extraction_metadata_without_geocoding() -> None:
    sig_id = uuid4()
    disease_id = uuid4()
    src_id = uuid4()
    now = datetime.now(UTC)

    fake_sig = FakeSignal(
        signal_id=sig_id,
        disease_id=disease_id,
        source_id=src_id,
        published_at=now,
        first_seen_at=now,
        is_official=True,
        credibility_tier=CredibilityTier.OFFICIAL,
        embedding=[1.0, 0.0],
        extraction={
            "signal_type": "outbreak_report",
            "title_english": "Outbreak in Beni",
            "brief": [
                {"slot": "what_where", "text": "Outbreak in Beni", "reported": True},
                {"slot": "counts", "text": "No count", "reported": False},
                {"slot": "timing", "text": "No date", "reported": False},
                {"slot": "spread", "text": "No spread", "reported": False},
                {"slot": "reporting", "text": "No reporting", "reported": False},
            ],
            "confidence": 0.95,
        },
    )
    session = FakeSession([FakeResult([(fake_sig, True, CredibilityTier.OFFICIAL)])])

    repo = SqlAlchemyEventRepository(session)
    signals = repo.signals_to_match(limit=10, stale=False)

    assert len(signals) == 1
    sig = signals[0]
    assert sig.signal_id == sig_id
    assert sig.disease_id == disease_id
    assert sig.source_is_official is True
    assert sig.credibility_tier == CredibilityTier.OFFICIAL
    assert sig.locations == ()
    assert sig.extraction is not None
    assert sig.extraction.signal_type == SignalType.OUTBREAK_REPORT
    assert sig.embedding is None

    # Assert executed statement checked processing_status
    stmt_str = str(session.executed[0])
    assert "processing_status" in stmt_str


def test_signals_to_match_does_not_infer_metadata_from_headline_text() -> None:
    sig_id = uuid4()
    source_id = uuid4()
    now = datetime.now(UTC)
    fake_sig = FakeSignal(
        signal_id=sig_id,
        disease_id=None,
        source_id=source_id,
        published_at=now,
        first_seen_at=now,
        is_official=True,
        credibility_tier=CredibilityTier.OFFICIAL,
    )
    fake_sig.title = "Measles Outbreak Grows to 98 Cases in Wisconsin"
    fake_sig.raw_text = "Public health officials confirmed the outbreak."
    disease = type(
        "DiseaseRow",
        (),
        {
            "id": uuid4(),
            "canonical_name": "Measles",
            "slug": "measles",
            "synonyms": [],
        },
    )()
    admin1 = type(
        "Admin1Row",
        (),
        {
            "name": "Wisconsin",
            "country_code": "US",
            "admin1_code": "WI",
            "alternate_names": [],
        },
    )()
    session = FakeSession(
        [
            FakeResult([(fake_sig, True, CredibilityTier.OFFICIAL)]),
            FakeResult([disease]),
            FakeResult([admin1]),
            FakeResult(["US"]),
        ]
    )

    signal = SqlAlchemyEventRepository(session).signals_to_match(limit=10)[0]

    assert signal.disease_id is None
    assert signal.locations == ()


class FakeEvent:
    def __init__(
        self,
        event_id,
        disease_id,
        first_signal_at,
        last_updated_at,
        country_code="CD",
        admin1="North Kivu",
    ) -> None:
        self.id = event_id
        self.disease_id = disease_id
        self.first_signal_at = first_signal_at
        self.last_updated_at = last_updated_at
        self.country_code = country_code
        self.admin1 = admin1
        self.title = f"Outbreak event {event_id}"
        self.created_at = last_updated_at


class FakeEventLocation:
    def __init__(
        self,
        event_id,
        role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        admin2="Beni",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    ) -> None:
        self.event_id = event_id
        self.location_role = role
        self.precision = precision
        self.country_code = country_code
        self.admin1 = admin1
        self.admin2 = admin2
        self.place_name = place_name
        self.latitude = latitude
        self.longitude = longitude


def test_candidate_events_filters_by_country_without_geospatial_sql() -> None:
    from episignal_backend.events.documents import StoryCluster

    disease_id = uuid4()
    now = datetime.now(UTC)

    # Place precision does not invoke retired geospatial narrowing.
    loc_place = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )
    sig_place = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=True,
        credibility_tier=CredibilityTier.OFFICIAL,
        published_at=now,
        first_seen_at=now,
        locations=(loc_place,),
    )
    cluster_place = StoryCluster(
        signals=(sig_place,),
    )

    ev_id = uuid4()
    fake_ev = FakeEvent(ev_id, disease_id, now, now)
    session_place = FakeSession(
        [
            FakeResult([fake_ev]),
        ]
    )

    repo_place = SqlAlchemyEventRepository(session_place)
    cands_place = repo_place.candidate_events(cluster_place, lookback_days=7, distance_km=50.0)

    assert len(cands_place) == 1
    assert cands_place[0].event_id == ev_id
    assert len(cands_place[0].locations) == 1
    sql_place = str(session_place.executed[0]).lower()
    assert "st_dwithin" not in sql_place

    # Admin1 precision uses the same country-level query.
    loc_admin1 = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.ADMIN1,
        country_code="CD",
        admin1="North Kivu",
        place_name=None,
        latitude=0.5,
        longitude=29.0,
    )
    sig_admin1 = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=True,
        credibility_tier=CredibilityTier.OFFICIAL,
        published_at=now,
        first_seen_at=now,
        locations=(loc_admin1,),
    )
    cluster_admin1 = StoryCluster(
        signals=(sig_admin1,),
    )

    session_admin1 = FakeSession(
        [
            FakeResult([fake_ev]),
        ]
    )
    repo_admin1 = SqlAlchemyEventRepository(session_admin1)
    cands_admin1 = repo_admin1.candidate_events(cluster_admin1)
    assert len(cands_admin1) == 1
    sql_admin1 = str(session_admin1.executed[0]).lower()
    assert "st_dwithin" not in sql_admin1
    assert "country_code" in sql_admin1


def test_candidates_are_bounded_by_lookback_and_limit() -> None:
    from episignal_backend.events.documents import StoryCluster

    disease_id = uuid4()
    now = datetime.now(UTC)
    cluster = StoryCluster(
        signals=(
            SignalForMatching(
                signal_id=uuid4(),
                disease_id=disease_id,
                source_id=uuid4(),
                source_is_official=True,
                credibility_tier=CredibilityTier.OFFICIAL,
                published_at=now,
                first_seen_at=now,
                locations=(
                    LocationForMatching(
                        location_role=LocationRole.PRIMARY,
                        precision=Precision.COUNTRY,
                        country_code="CD",
                    ),
                ),
            ),
        )
    )
    session = FakeSession([FakeResult([])])

    SqlAlchemyEventRepository(session).candidate_events(cluster, lookback_days=7, limit=20)

    statement = session.executed[0]
    parameters = statement.compile().params.values()
    cutoffs = [value for value in parameters if isinstance(value, datetime)]
    assert len(cutoffs) == 1
    assert cutoffs[0] <= datetime.now(UTC) - timedelta(days=7)
    assert statement._limit_clause.value == 20
    assert "events.last_updated_at desc" in str(statement).lower()


def test_candidate_query_is_constrained_to_the_cluster_disease() -> None:
    from episignal_backend.events.documents import StoryCluster

    disease_id = uuid4()
    now = datetime.now(UTC)
    cluster = StoryCluster(
        signals=(
            SignalForMatching(
                signal_id=uuid4(),
                disease_id=disease_id,
                source_id=uuid4(),
                source_is_official=True,
                credibility_tier=CredibilityTier.OFFICIAL,
                published_at=now,
                first_seen_at=now,
                locations=(
                    LocationForMatching(
                        location_role=LocationRole.PRIMARY,
                        precision=Precision.COUNTRY,
                        country_code="CD",
                    ),
                ),
            ),
        )
    )
    session = FakeSession([FakeResult([])])

    SqlAlchemyEventRepository(session).candidate_events(cluster, lookback_days=7, limit=20)

    assert disease_id in session.executed[0].compile().params.values()


def test_a_cluster_without_geography_has_no_candidates() -> None:
    from episignal_backend.events.documents import StoryCluster

    disease_id = uuid4()
    now = datetime.now(UTC)
    cluster = StoryCluster(
        signals=(
            SignalForMatching(
                signal_id=uuid4(),
                disease_id=disease_id,
                source_id=uuid4(),
                source_is_official=True,
                credibility_tier=CredibilityTier.OFFICIAL,
                published_at=now,
                first_seen_at=now,
                locations=(),
            ),
        )
    )
    event = FakeEvent(uuid4(), disease_id, now, now, country_code=None, admin1=None)
    session = FakeSession([FakeResult([event]), FakeResult([])])

    candidates = SqlAlchemyEventRepository(session).candidate_events(
        cluster, lookback_days=7, limit=20
    )

    assert candidates == ()
    assert session.executed == []


def test_candidate_events_do_not_load_embeddings() -> None:
    from episignal_backend.events.documents import StoryCluster

    disease_id = uuid4()
    now = datetime.now(UTC)
    location = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )
    cluster = StoryCluster(
        signals=(
            SignalForMatching(
                signal_id=uuid4(),
                disease_id=disease_id,
                source_id=uuid4(),
                source_is_official=True,
                credibility_tier=CredibilityTier.OFFICIAL,
                published_at=now,
                first_seen_at=now,
                locations=(location,),
            ),
        )
    )
    event = FakeEvent(uuid4(), disease_id, now, now)
    session = FakeSession([FakeResult([event])])

    candidates = SqlAlchemyEventRepository(session).candidate_events(cluster)

    assert candidates[0].representative_embedding is None


def test_create_event_inserts_event_row_and_returns_candidate() -> None:
    from episignal_backend.events.documents import StoryCluster
    from episignal_backend.models import Event

    disease_id = uuid4()
    now = datetime.now(UTC)
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
    sig = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=True,
        credibility_tier=CredibilityTier.OFFICIAL,
        published_at=now,
        first_seen_at=now,
        locations=(loc,),
    )
    cluster = StoryCluster(signals=(sig,))

    session = FakeSession()
    repo = SqlAlchemyEventRepository(session)
    candidate = repo.create_event(cluster)

    assert candidate.disease_id == disease_id
    assert len(candidate.locations) == 1
    assert candidate.locations[0].place_name == "Beni"
    assert candidate.first_signal_at == now

    # Check added event model instance
    assert len(session.added) == 1
    added_event = session.added[0]
    assert isinstance(added_event, Event)
    assert added_event.disease_id == disease_id
    assert added_event.country_code == "CD"
    assert added_event.latitude == 0.49
    assert added_event.longitude == 29.47
    assert added_event.public_id.startswith("EVT-")


def test_attach_signal_inserts_event_signal_row() -> None:
    from episignal_backend.db.types import RelationshipType
    from episignal_backend.models import EventSignal

    ev_id = uuid4()
    sig_id = uuid4()

    session = FakeSession()
    repo = SqlAlchemyEventRepository(session)
    repo.attach_signal(
        event_id=ev_id,
        signal_id=sig_id,
        relationship_type=RelationshipType.INITIAL_REPORT,
        match_score=0.92,
        is_primary=True,
    )

    assert len(session.added) == 1
    added_rel = session.added[0]
    assert isinstance(added_rel, EventSignal)
    assert added_rel.event_id == ev_id
    assert added_rel.signal_id == sig_id
    assert added_rel.relationship_type == RelationshipType.INITIAL_REPORT
    assert added_rel.match_score == 0.92
    assert added_rel.is_primary is True


def test_record_observation_inserts_grounded_counts_and_preserves_nulls() -> None:
    from episignal_backend.ai.schema import (
        BriefPoint,
        BriefSlot,
        Epidemiology,
        Extraction,
        GroundedCount,
    )
    from episignal_backend.models import EventObservation

    ev_id = uuid4()
    sig_id = uuid4()
    now = datetime.now(UTC)

    extraction = Extraction(
        signal_type=SignalType.OUTBREAK_REPORT,
        title_english="35 cases reported",
        brief=(
            BriefPoint(slot=BriefSlot.WHAT_WHERE, text="35 cases reported", reported=True),
            BriefPoint(slot=BriefSlot.COUNTS, text="35 cases", reported=True),
            BriefPoint(slot=BriefSlot.TIMING, text="No date", reported=False),
            BriefPoint(slot=BriefSlot.SPREAD, text="No spread", reported=False),
            BriefPoint(slot=BriefSlot.REPORTING, text="No reporting", reported=False),
        ),
        epidemiology=Epidemiology(
            total_cases=GroundedCount(value=35, source_span="35 cases"),
            # deaths is None, confirmed_cases is None!
        ),
        confidence=0.88,
    )
    sig = SignalForMatching(
        signal_id=sig_id,
        disease_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.HIGH,
        published_at=now,
        first_seen_at=now,
        extraction=extraction,
    )

    session = FakeSession()
    repo = SqlAlchemyEventRepository(session)
    repo.record_observation(event_id=ev_id, signal=sig)

    assert len(session.added) == 1
    obs = session.added[0]
    assert isinstance(obs, EventObservation)
    assert obs.event_id == ev_id
    assert obs.signal_id == sig_id
    assert obs.total_cases == 35
    # Crucial invariant: null counts must be None, NEVER 0
    assert obs.deaths is None
    assert obs.confirmed_cases is None
    assert obs.suspected_cases is None
    assert obs.extraction_confidence == 0.88


def test_record_observation_is_idempotent_for_a_stale_rerun() -> None:
    from episignal_backend.models import EventObservation

    ev_id = uuid4()
    sig_id = uuid4()
    now = datetime.now(UTC)
    sig = SignalForMatching(
        signal_id=sig_id,
        disease_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.HIGH,
        published_at=now,
        first_seen_at=now,
    )

    # First call: the dedup query finds nothing, so an observation is added.
    session = FakeSession([FakeResult([])])
    repo = SqlAlchemyEventRepository(session)
    repo.record_observation(event_id=ev_id, signal=sig)
    assert len(session.added) == 1

    # Stale re-run: the dedup query finds the existing row, so nothing new is
    # added and the earlier observation is never overwritten or duplicated.
    session = FakeSession([FakeResult([EventObservation(event_id=ev_id, signal_id=sig_id)])])
    repo = SqlAlchemyEventRepository(session)
    repo.record_observation(event_id=ev_id, signal=sig)
    assert session.added == []


def test_add_locations_inserts_event_location_rows() -> None:
    from episignal_backend.models import EventLocation

    ev_id = uuid4()
    loc1 = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )
    loc2 = LocationForMatching(
        location_role=LocationRole.AFFECTED_AREA,
        precision=Precision.ADMIN1,
        country_code="CD",
        admin1="Ituri",
        place_name=None,
        latitude=1.5,
        longitude=30.0,
    )

    session = FakeSession()
    repo = SqlAlchemyEventRepository(session)
    repo.add_locations(event_id=ev_id, locations=[loc1, loc2])

    assert len(session.added) == 2
    for item in session.added:
        assert isinstance(item, EventLocation)
        assert item.event_id == ev_id


def test_apply_scores_executes_update_on_event() -> None:
    from episignal_backend.db.types import VerificationStatus
    from sqlalchemy import Update

    ev_id = uuid4()
    session = FakeSession()
    repo = SqlAlchemyEventRepository(session)
    repo.apply_scores(
        event_id=ev_id,
        early_signal_score=0.75,
        evidence_score=0.60,
        verification_status=VerificationStatus.HIGH_CREDIBILITY,
    )

    assert len(session.executed) == 1
    stmt = session.executed[0]
    assert isinstance(stmt, Update)
    stmt_str = str(stmt).lower()
    assert "events" in stmt_str
    assert "early_signal_score" in stmt_str
    assert "evidence_score" in stmt_str
    assert "verification_status" in stmt_str


def test_store_summary_persists_structured_flash_brief_and_denormalized_text() -> None:
    from episignal_backend.models import EventSummary

    event_id = uuid4()
    session = FakeSession([FakeResult(None), FakeResult(2)])
    repo = SqlAlchemyEventRepository(session)

    version = repo.store_summary(
        event_id=event_id,
        headline="Dengue Outbreak: Chiang Mai — Increasing",
        summary="Dengue Outbreak: Chiang Mai — Increasing",
        trajectory="Increasing",
        snapshot={"cases": "68 confirmed cases"},
        key_driver="Ongoing local transmission.",
        response="Case investigation is underway.",
        risk="Risk remains regional.",
        model_id="fake-summary-model",
        source_signal_ids=[],
        counts=None,
    )

    assert version == 1
    assert isinstance(session.added[0], EventSummary)
    assert session.added[0].trajectory == "Increasing"
    assert session.added[0].snapshot == {"cases": "68 confirmed cases"}
    assert session.added[0].key_driver == "Ongoing local transmission."
    update_statement = session.executed[-1]
    assert "status" not in {key.key for key in update_statement._values}


def test_store_summary_serializes_source_signal_ids_for_jsonb() -> None:
    event_id = uuid4()
    signal_id = uuid4()
    session = FakeSession([FakeResult(None), FakeResult(1)])
    repo = SqlAlchemyEventRepository(session)

    repo.store_summary(
        event_id=event_id,
        headline="Dengue Outbreak: Chiang Mai — Increasing",
        summary="Dengue Outbreak: Chiang Mai — Increasing",
        trajectory="Increasing",
        snapshot={"cases": "68 confirmed cases"},
        key_driver="Ongoing local transmission.",
        response="Case investigation is underway.",
        risk="Risk remains regional.",
        model_id="fake-summary-model",
        source_signal_ids=[signal_id],
        counts=None,
    )

    assert session.added[0].source_signal_ids == [str(signal_id)]


def test_a_stored_extraction_survives_its_version_key() -> None:
    payload = {
        "signal_type": "outbreak_report",
        "source_language": "en",
        "title_english": "Cholera outbreak reported in Luanda",
        "brief": [
            {"slot": "what_where", "text": "Cholera in Luanda, Angola.", "reported": True},
            {"slot": "counts", "text": "327 confirmed cases.", "reported": True},
            {"slot": "timing", "text": "As of 25 August 2026.", "reported": True},
            {"slot": "spread", "text": "Acquired locally.", "reported": True},
            {"slot": "reporting", "text": "Reported by the health ministry.", "reported": True},
        ],
        "epidemiology": {"confirmed_cases": {"value": 327, "source_span": "327 confirmed cases"}},
        "confidence": 0.9,
        EXTRACTION_VERSION_KEY: EXTRACTION_SCHEMA_VERSION,
    }

    extraction = read_stored_extraction(payload)

    assert extraction is not None
    assert extraction.epidemiology.confirmed_cases is not None
    assert extraction.epidemiology.confirmed_cases.value == 327


def test_an_unreadable_extraction_is_absence_rather_than_an_exception() -> None:
    assert read_stored_extraction({"signal_type": "not_a_type"}) is None


def test_event_repository_has_no_human_review_write_path() -> None:
    repo = SqlAlchemyEventRepository(FakeSession())

    assert not hasattr(repo, "open_review")
