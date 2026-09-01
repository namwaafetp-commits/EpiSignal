from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from episignal_backend.db.types import CredibilityTier, LocationRole, Precision, ProcessingStatus
from episignal_backend.events.assemble import run_event_assembly
from episignal_backend.events.cluster import build_clusters
from episignal_backend.events.documents import LocationForMatching, SignalForMatching, StoryCluster
from episignal_backend.events.match import decide
from episignal_backend.events.repository import SqlAlchemyEventRepository
from episignal_backend.pipeline_runner import parse_arguments
from episignal_backend.requeue import requeue_historical_extractions
from episignal_backend.schedule.chains import DAILY_CHAIN
from episignal_backend.schedule.documents import StageName
from episignal_backend.schedule.stages import build_stage_runners

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)


def test_daily_runtime_is_lean_mvp_chain() -> None:
    assert DAILY_CHAIN == (
        StageName.INGEST_WHO,
        StageName.DISCOVER,
        StageName.DEDUPE,
        StageName.CLASSIFY,
        StageName.RETRIEVE,
        StageName.EXTRACT,
        StageName.MATCH,
        StageName.SUMMARIZE,
    )


def test_stage_runners_expose_only_lean_mvp_runtime() -> None:
    runners = build_stage_runners(window=SimpleNamespace(start=NOW, end=NOW))

    assert tuple(runners) == DAILY_CHAIN


def test_direct_country_location_needs_no_coordinates() -> None:
    location = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="TH",
    )

    assert location.latitude is None
    assert location.longitude is None


def test_match_repository_does_not_read_triage_country_without_extraction() -> None:
    signal_id = uuid4()
    disease_id = uuid4()
    signal = SimpleNamespace(
        id=signal_id,
        disease_id=disease_id,
        source_id=uuid4(),
        triage_country_code="TH",
        triage_admin1=None,
        published_at=NOW,
        first_seen_at=NOW,
        title="Dengue outbreak in Thailand",
        ai_extraction=None,
    )
    session = SimpleNamespace(
        execute=lambda statement: SimpleNamespace(
            all=lambda: [(signal, False, CredibilityTier.MEDIUM)]
        )
    )

    result = SqlAlchemyEventRepository(session).signals_to_match(limit=1)

    assert result[0].locations == ()
    assert result[0].disease_id is None


@pytest.mark.parametrize(
    ("country", "expected"),
    (("Thailand", "TH"), ("United States", "US"), ("Ruritania", None)),
)
def test_match_repository_resolves_extraction_country_aliases(
    country: str, expected: str | None
) -> None:
    signal_id = uuid4()
    extraction = _valid_extraction()
    extraction["locations"] = [{"role": "primary", "country": country}]
    signal = SimpleNamespace(
        id=signal_id,
        disease_id=None,
        source_id=uuid4(),
        triage_country_code=None,
        triage_admin1=None,
        published_at=NOW,
        first_seen_at=NOW,
        title="Disease report",
        ai_extraction=extraction,
    )
    session = SimpleNamespace(
        execute=lambda statement: SimpleNamespace(
            all=lambda: [(signal, False, CredibilityTier.MEDIUM)]
        )
    )

    result = SqlAlchemyEventRepository(session).signals_to_match(limit=1)

    if expected is None:
        assert result[0].locations == ()
    else:
        assert result[0].locations[0].country_code == expected


def test_extraction_country_takes_priority_over_triage_country() -> None:
    extraction = _valid_extraction()
    extraction["locations"] = [{"role": "primary", "country": "Thailand"}]
    signal = SimpleNamespace(
        id=uuid4(),
        disease_id=None,
        source_id=uuid4(),
        triage_country_code="UG",
        triage_admin1=None,
        published_at=NOW,
        first_seen_at=NOW,
        title="Disease report",
        ai_extraction=extraction,
    )
    session = SimpleNamespace(
        execute=lambda statement: SimpleNamespace(
            all=lambda: [(signal, False, CredibilityTier.MEDIUM)]
        )
    )

    result = SqlAlchemyEventRepository(session).signals_to_match(limit=1)

    assert result[0].locations[0].country_code == "TH"


def test_same_disease_and_country_can_attach_without_admin1() -> None:
    disease_id = uuid4()
    location = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="TH",
    )
    signal = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=NOW,
        first_seen_at=NOW,
        locations=(location,),
    )
    candidate = SimpleNamespace(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(location,),
        first_signal_at=NOW - timedelta(days=1),
        last_updated_at=NOW,
    )

    decision = decide(StoryCluster(signals=(signal,)), [candidate], threshold=0.60)

    assert decision.event_id == candidate.event_id


def test_exact_disease_text_and_country_cluster_without_disease_id() -> None:
    location = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="TH",
    )
    first = SignalForMatching(
        signal_id=uuid4(),
        disease_id=None,
        disease_text=" Dengue ",
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=NOW,
        first_seen_at=NOW,
        locations=(location,),
    )
    second = first.model_copy(update={"signal_id": uuid4(), "disease_text": "dengue"})

    clusters, unclusterable = build_clusters((first, second), window_days=7)

    assert len(clusters) == 1
    assert len(clusters[0].signals) == 2
    assert unclusterable == ()


def test_exact_disease_text_and_country_can_attach_without_disease_id() -> None:
    location = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="TH",
    )
    signal = SignalForMatching(
        signal_id=uuid4(),
        disease_id=None,
        disease_text="Dengue",
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=NOW,
        first_seen_at=NOW,
        locations=(location,),
    )
    candidate = SimpleNamespace(
        event_id=uuid4(),
        disease_id=None,
        disease_text=" dengue ",
        locations=(location,),
        first_signal_at=NOW - timedelta(days=1),
        last_updated_at=NOW,
    )

    decision = decide(StoryCluster(signals=(signal,)), [candidate], threshold=0.60)

    assert decision.event_id == candidate.event_id


def test_null_disease_event_uses_attached_extraction_text_as_candidate_identity() -> None:
    event = SimpleNamespace(
        id=uuid4(),
        disease_id=None,
        country_code="TH",
        admin1=None,
        admin2=None,
        place_name=None,
        first_signal_at=NOW - timedelta(days=1),
        created_at=NOW - timedelta(days=1),
        last_updated_at=NOW,
        title="Dengue event",
    )
    extraction = _valid_extraction()
    extraction["disease"] = {"name": "Dengue", "confidence": 0.9}
    results = [
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [event])),
        SimpleNamespace(all=lambda: [(event.id, True, extraction)]),
    ]

    class Session:
        def execute(self, statement):
            return results.pop(0)

    signal = SignalForMatching(
        signal_id=uuid4(),
        disease_id=None,
        disease_text=" dengue ",
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=NOW,
        first_seen_at=NOW,
        locations=(
            LocationForMatching(
                location_role=LocationRole.PRIMARY,
                precision=Precision.COUNTRY,
                country_code="TH",
            ),
        ),
    )

    candidates = SqlAlchemyEventRepository(Session()).candidate_events(
        StoryCluster(signals=(signal,)),
        lookback_days=7,
    )

    assert candidates[0].disease_text == "dengue"


class _AssemblyRepository:
    def __init__(self, signal: SignalForMatching, candidate=None) -> None:
        self.signal = signal
        self.candidate = candidate
        self.created = []
        self.matched = []
        self.reviews = []

    def signals_to_match(self, limit: int, *, stale: bool = False):
        return (self.signal,)

    def candidate_events(self, cluster, **kwargs):
        return (self.candidate,) if self.candidate is not None else ()

    def create_event(self, cluster):
        event = SimpleNamespace(
            event_id=uuid4(),
            disease_id=cluster.disease_id,
            locations=(cluster.representative_location,) if cluster.representative_location else (),
            first_signal_at=NOW,
            last_updated_at=NOW,
        )
        self.created.append(event)
        return event

    def attach_signal(self, *args, **kwargs):
        pass

    def record_observation(self, *args, **kwargs):
        pass

    def add_locations(self, *args, **kwargs):
        pass

    def apply_scores(self, *args, **kwargs):
        pass

    def mark_matched(self, signal_id):
        self.matched.append(signal_id)

    def open_review(self, *args, **kwargs):
        self.reviews.append(args)

    def latest_brief(self, event_id):
        return None

    def apply_delta(self, *args, **kwargs):
        pass

    def record_ai_request(self, *args, **kwargs):
        pass

    def commit(self):
        pass


def test_unresolved_disease_still_creates_unmapped_event() -> None:
    signal = SignalForMatching(
        signal_id=uuid4(),
        disease_id=None,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.UNKNOWN,
        published_at=NOW,
        first_seen_at=NOW,
        locations=(),
    )
    repo = _AssemblyRepository(signal)

    result = run_event_assembly(repo)

    assert result.events_created == 1
    assert result.signals_attached == 1
    assert repo.reviews == []
    assert repo.matched == [signal.signal_id]


def test_unresolved_country_still_creates_event_without_review() -> None:
    signal = SignalForMatching(
        signal_id=uuid4(),
        disease_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.UNKNOWN,
        published_at=NOW,
        first_seen_at=NOW,
        locations=(
            LocationForMatching(
                location_role=LocationRole.PRIMARY,
                precision=Precision.UNRESOLVED,
                place_name="Unknown place",
            ),
        ),
    )
    repo = _AssemblyRepository(signal)

    result = run_event_assembly(repo)

    assert result.events_created == 1
    assert result.signals_attached == 1
    assert repo.reviews == []


def test_ambiguous_match_creates_new_event_without_judge_or_review() -> None:
    disease_id = uuid4()
    location = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="TH",
    )
    signal = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=NOW,
        first_seen_at=NOW,
        locations=(location,),
    )
    candidate = SimpleNamespace(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(location,),
        first_signal_at=NOW - timedelta(days=1),
        last_updated_at=NOW,
    )
    repo = _AssemblyRepository(signal, candidate)

    result = run_event_assembly(repo, match_threshold=0.75, review_threshold=0.55)

    assert result.events_created == 1
    assert result.signals_attached == 1
    assert result.ambiguous_judged == 0
    assert repo.reviews == []


def test_legacy_status_is_not_part_of_runtime_chain() -> None:
    assert ProcessingStatus.NEEDS_REVIEW.value == "needs_review"
    assert StageName.GEOCODE not in DAILY_CHAIN
    assert StageName.PREGROUP not in DAILY_CHAIN
    assert StageName.EMBED not in DAILY_CHAIN
    assert StageName.INGEST_ECDC not in DAILY_CHAIN


def test_requeue_switch_runs_match_and_summary_only() -> None:
    arguments = parse_arguments(["--requeue-existing"])

    assert arguments.requeue_existing is True


class _RequeueSession:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.statements = []
        self.committed = False

    def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: self.rows))

    def commit(self):
        self.committed = True


def _valid_extraction() -> dict:
    absence = {"reported": False, "text": "Not reported"}
    return {
        "signal_type": "outbreak_report",
        "title_english": "Unknown disease report",
        "brief": [
            {"slot": "what_where", **absence},
            {"slot": "counts", **absence},
            {"slot": "timing", **absence},
            {"slot": "spread", **absence},
            {"slot": "reporting", **absence},
        ],
        "confidence": 0.8,
    }


def test_requeue_selects_only_valid_nonduplicate_nonirrelevant_rows() -> None:
    eligible = SimpleNamespace(
        ai_extraction=_valid_extraction(),
        processing_status=ProcessingStatus.NEEDS_REVIEW,
        duplicate_of_signal_id=None,
        public_health_relevant=None,
        raw_text=None,
    )
    irrelevant = SimpleNamespace(
        ai_extraction=_valid_extraction(),
        processing_status=ProcessingStatus.NEEDS_REVIEW,
        duplicate_of_signal_id=None,
        public_health_relevant=False,
        raw_text="body",
    )
    invalid = SimpleNamespace(
        ai_extraction={"not": "an extraction"},
        processing_status=ProcessingStatus.NEEDS_REVIEW,
        duplicate_of_signal_id=None,
        public_health_relevant=True,
        raw_text="body",
    )
    session = _RequeueSession([eligible, irrelevant, invalid])

    result = requeue_historical_extractions(session)

    assert result.examined == 3
    assert result.requeued == 1
    assert eligible.processing_status is ProcessingStatus.EXTRACTED
    assert irrelevant.processing_status is ProcessingStatus.NEEDS_REVIEW
    assert invalid.processing_status is ProcessingStatus.NEEDS_REVIEW
    assert session.committed is True
