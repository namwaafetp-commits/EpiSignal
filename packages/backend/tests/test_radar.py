from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from episignal_backend.ai.schema import BriefPoint, BriefSlot
from episignal_backend.db.types import (
    CredibilityTier,
    LocationRole,
    PipelineChain,
    PipelineRunStatus,
    PipelineTrigger,
    Precision,
    ProcessingStatus,
    SignalType,
    VerificationStatus,
)
from episignal_backend.models import PipelineRun, SignalLocation
from episignal_backend.radar import (
    EventContextStatus,
    PipelineFailure,
    PipelineRunItem,
    PipelineRunPage,
    RadarEventContext,
    RadarItem,
    RadarLocation,
    RadarPage,
    RadarSource,
    choose_representative_location,
    query_pipeline_runs,
    query_radar,
)
from episignal_backend.schedule.documents import StageName


def test_event_context_status_values() -> None:
    assert EventContextStatus.NONE == "none"
    assert EventContextStatus.ATTACHED == "attached"
    assert EventContextStatus.AMBIGUOUS == "ambiguous"
    assert len(list(EventContextStatus)) == 3


def test_radar_contracts_are_frozen_and_have_exact_fields() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    sig_id = uuid4()
    run_id = uuid4()

    source = RadarSource(
        name="WHO",
        url="https://who.int/report",
        is_official=True,
        credibility_tier=CredibilityTier.OFFICIAL,
    )
    with pytest.raises(FrozenInstanceError):
        source.name = "ECDC"  # type: ignore[misc]

    location = RadarLocation(
        role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        label="Kano",
        country_code="NG",
        latitude=12.0,
        longitude=8.5,
    )
    with pytest.raises(FrozenInstanceError):
        location.label = "Lagos"  # type: ignore[misc]

    event = RadarEventContext(
        public_id="EVT-2026-001",
        verification_status=VerificationStatus.OFFICIALLY_CONFIRMED,
        early_signal_score=0.85,
        evidence_score=0.92,
    )
    with pytest.raises(FrozenInstanceError):
        event.public_id = "EVT-2"  # type: ignore[misc]

    brief = (
        BriefPoint(slot=BriefSlot.WHAT_WHERE, text="Outbreak of Cholera in Kano.", reported=True),
        BriefPoint(slot=BriefSlot.COUNTS, text="50 dead.", reported=True),
        BriefPoint(slot=BriefSlot.TIMING, text="Timeline not reported.", reported=False),
        BriefPoint(slot=BriefSlot.SPREAD, text="Spread to adjacent districts.", reported=True),
        BriefPoint(slot=BriefSlot.REPORTING, text="Reported by MoH.", reported=True),
    )

    item = RadarItem(
        id=sig_id,
        title_english="Cholera outbreak in Kano",
        brief=brief,
        signal_type=SignalType.OUTBREAK_REPORT,
        processing_status=ProcessingStatus.EXTRACTED,
        published_at=now,
        first_seen_at=now,
        source=source,
        extraction_confidence=0.95,
        location=location,
        event_context_status=EventContextStatus.ATTACHED,
        event=event,
    )
    with pytest.raises(FrozenInstanceError):
        item.title_english = "Other"  # type: ignore[misc]

    page = RadarPage(
        items=(item,),
        window_start=now,
        window_end=now,
        hours=48,
        limit=50,
    )
    with pytest.raises(FrozenInstanceError):
        page.hours = 24  # type: ignore[misc]

    failure = PipelineFailure(stage=StageName.EXTRACT, error="TimeoutError")
    with pytest.raises(FrozenInstanceError):
        failure.error = None  # type: ignore[misc]

    run_item = PipelineRunItem(
        id=run_id,
        chain=PipelineChain.DAILY,
        trigger=PipelineTrigger.SCHEDULED,
        status=PipelineRunStatus.SUCCEEDED,
        started_at=now,
        finished_at=now,
        window_start=now,
        window_end=now,
        stage_counts={"extract": {"extracted": 5}},
        backlog={"extracted": 0},
        failures=(),
        is_stale=False,
    )
    with pytest.raises(FrozenInstanceError):
        run_item.is_stale = True  # type: ignore[misc]

    run_page = PipelineRunPage(items=(run_item,), limit=20)
    with pytest.raises(FrozenInstanceError):
        run_page.limit = 10  # type: ignore[misc]


def _make_location(
    *,
    id: UUID | None = None,
    role: LocationRole = LocationRole.PRIMARY,
    precision: Precision = Precision.PLACE,
    resolved_name: str | None = None,
    place_name: str | None = None,
    admin2: str | None = None,
    admin1: str | None = None,
    country_name: str | None = None,
    country_code: str | None = "NG",
    latitude: float | None = 12.0,
    longitude: float | None = 8.5,
) -> SignalLocation:
    loc = SignalLocation(
        signal_id=uuid4(),
        location_role=role,
        precision=precision,
        resolved_name=resolved_name,
        place_name=place_name,
        admin2=admin2,
        admin1=admin1,
        country_name=country_name,
        country_code=country_code,
        latitude=latitude,
        longitude=longitude,
    )
    loc.id = id or uuid4()
    return loc


def test_choose_representative_location_returns_none_when_empty() -> None:
    assert choose_representative_location([]) is None


def test_choose_representative_location_prefers_primary_role() -> None:
    affected = _make_location(
        role=LocationRole.AFFECTED_AREA,
        precision=Precision.PLACE,
        place_name="Specific Village",
    )
    primary = _make_location(
        role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_name="Nigeria",
    )

    chosen = choose_representative_location([affected, primary])
    assert chosen is not None
    assert chosen.role == LocationRole.PRIMARY
    assert chosen.precision == Precision.COUNTRY
    assert chosen.label == "Nigeria"


def test_choose_representative_location_falls_back_to_all_roles_if_no_primary() -> None:
    exposure = _make_location(
        role=LocationRole.EXPOSURE,
        precision=Precision.COUNTRY,
        country_name="Angola",
    )
    affected = _make_location(
        role=LocationRole.AFFECTED_AREA,
        precision=Precision.PLACE,
        place_name="Luanda",
    )

    chosen = choose_representative_location([exposure, affected])
    assert chosen is not None
    assert chosen.role == LocationRole.AFFECTED_AREA
    assert chosen.precision == Precision.PLACE
    assert chosen.label == "Luanda"


@pytest.mark.parametrize(
    ("higher_prec", "lower_prec"),
    [
        (Precision.PLACE, Precision.ADMIN2),
        (Precision.ADMIN2, Precision.ADMIN1),
        (Precision.ADMIN1, Precision.COUNTRY),
        (Precision.COUNTRY, Precision.UNRESOLVED),
    ],
)
def test_choose_representative_location_precision_ordering(
    higher_prec: Precision, lower_prec: Precision
) -> None:
    loc_high = _make_location(precision=higher_prec, place_name="High")
    loc_low = _make_location(precision=lower_prec, place_name="Low")

    chosen = choose_representative_location([loc_low, loc_high])
    assert chosen is not None
    assert chosen.precision == higher_prec


def test_choose_representative_location_tie_breaks_by_location_id_ascending() -> None:
    id_a = UUID("00000000-0000-0000-0000-000000000001")
    id_b = UUID("00000000-0000-0000-0000-000000000002")

    loc_b = _make_location(id=id_b, place_name="Location B", precision=Precision.PLACE)
    loc_a = _make_location(id=id_a, place_name="Location A", precision=Precision.PLACE)

    chosen = choose_representative_location([loc_b, loc_a])
    assert chosen is not None
    assert chosen.label == "Location A"


def test_choose_representative_location_label_fallbacks() -> None:
    # 1. resolved_name wins
    loc1 = _make_location(
        resolved_name="Resolved City",
        place_name="Extracted Place",
        admin2="District",
        admin1="State",
        country_name="Country",
    )
    assert choose_representative_location([loc1]).label == "Resolved City"  # type: ignore[union-attr]

    # 2. place_name wins if no resolved_name
    loc2 = _make_location(
        place_name="Extracted Place",
        admin2="District",
        admin1="State",
        country_name="Country",
    )
    assert choose_representative_location([loc2]).label == "Extracted Place"  # type: ignore[union-attr]

    # 3. admin2 wins if no place_name
    loc3 = _make_location(admin2="District", admin1="State", country_name="Country")
    assert choose_representative_location([loc3]).label == "District"  # type: ignore[union-attr]

    # 4. admin1 wins if no admin2
    loc4 = _make_location(admin1="State", country_name="Country")
    assert choose_representative_location([loc4]).label == "State"  # type: ignore[union-attr]

    # 5. country_name wins if no admin1
    loc5 = _make_location(country_name="Country")
    assert choose_representative_location([loc5]).label == "Country"  # type: ignore[union-attr]


def test_choose_representative_location_unresolved_or_missing_coords_returns_null_coords() -> None:
    # Unresolved precision
    unres = _make_location(
        precision=Precision.UNRESOLVED,
        place_name="Mystery Place",
        latitude=10.0,
        longitude=20.0,
    )
    chosen_unres = choose_representative_location([unres])
    assert chosen_unres is not None
    assert chosen_unres.precision == Precision.UNRESOLVED
    assert chosen_unres.latitude is None
    assert chosen_unres.longitude is None

    # Missing latitude
    half_lat = _make_location(precision=Precision.PLACE, latitude=None, longitude=20.0)
    chosen_half_lat = choose_representative_location([half_lat])
    assert chosen_half_lat is not None
    assert chosen_half_lat.latitude is None
    assert chosen_half_lat.longitude is None

    # Missing longitude
    half_lon = _make_location(precision=Precision.PLACE, latitude=10.0, longitude=None)
    chosen_half_lon = choose_representative_location([half_lon])
    assert chosen_half_lon is not None
    assert chosen_half_lon.latitude is None
    assert chosen_half_lon.longitude is None


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> Any:
        return self._value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = results or []
        self.executed: list[Any] = []

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return self._results.pop(0) if self._results else FakeResult([])

    def scalars(self, statement: Any) -> Any:
        self.executed.append(statement)
        return self._results.pop(0) if self._results else FakeResult([])


class FakeSignalRow:
    def __init__(
        self,
        *,
        id: UUID | None = None,
        url: str = "https://publisher.com/article/1",
        processing_status: ProcessingStatus = ProcessingStatus.EXTRACTED,
        signal_type: SignalType = SignalType.OUTBREAK_REPORT,
        published_at: datetime | None = None,
        first_seen_at: datetime | None = None,
        ai_extraction: dict[str, Any] | None = None,
        title: str = "Cholera in Luanda",
        raw_text: str | None = "Health officials reported 50 cholera cases.",
        content_hash: str | None = None,
        source_name: str = "Health Ministry",
        source_is_official: bool = True,
        source_credibility_tier: CredibilityTier = CredibilityTier.OFFICIAL,
    ) -> None:
        self.id = id or uuid4()
        self.url = url
        self.processing_status = processing_status
        self.signal_type = signal_type
        self.published_at = published_at
        self.first_seen_at = first_seen_at or datetime(2026, 8, 28, 10, 0, tzinfo=UTC)
        self.title = title
        self.raw_text = raw_text
        if content_hash is not None:
            self.content_hash = content_hash
        else:
            from episignal_backend.ingestion.fingerprint import content_hash as compute_hash

            self.content_hash = compute_hash(title, raw_text or "")
        self.ai_extraction = (
            ai_extraction
            if ai_extraction is not None
            else {
                "extraction_schema_version": 2,
                "signal_type": "outbreak_report",
                "title_english": "Cholera in Luanda",
                "source_language": "en",
                "confidence": 0.95,
                "brief": [
                    {"slot": "what_where", "text": "Cholera in Luanda.", "reported": True},
                    {"slot": "counts", "text": "50 cases.", "reported": True},
                    {"slot": "timing", "text": "No dates.", "reported": False},
                    {"slot": "spread", "text": "No spread.", "reported": False},
                    {"slot": "reporting", "text": "Reported by MoH.", "reported": True},
                ],
            }
        )
        self.source_name = source_name
        self.source_is_official = source_is_official
        self.source_credibility_tier = source_credibility_tier


class FakeEventRow:
    def __init__(
        self,
        *,
        signal_id: UUID,
        public_id: str = "EVT-2026-001",
        verification_status: VerificationStatus = VerificationStatus.OFFICIALLY_CONFIRMED,
        early_signal_score: float | None = 0.85,
        evidence_score: float | None = 0.92,
    ) -> None:
        self.signal_id = signal_id
        self.public_id = public_id
        self.verification_status = verification_status
        self.early_signal_score = early_signal_score
        self.evidence_score = evidence_score


def test_query_radar_statement_structure() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    session = FakeSession()

    page = query_radar(session, now=now, hours=48, limit=50)
    assert page.items == ()
    assert page.hours == 48
    assert page.limit == 50
    assert page.window_end == now
    assert page.window_start == datetime(2026, 8, 26, 12, 0, tzinfo=UTC)

    statement = str(session.executed[0])
    assert "FROM signals" in statement
    assert "JOIN sources" in statement
    assert "signals.processing_status IN" in statement
    assert "signals.duplicate_of_signal_id IS NULL" in statement
    assert "coalesce(signals.published_at, signals.first_seen_at)" in statement
    assert "LIMIT" in statement
    assert "OFFSET" in statement


def test_query_radar_assembly_unmatched_signal() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    sig_id = uuid4()
    sig_row = FakeSignalRow(id=sig_id)

    # 1st execute: signal rows
    # 2nd execute: locations
    # 3rd execute: events
    session = FakeSession(
        [
            FakeResult([sig_row]),
            FakeResult([]),
            FakeResult([]),
        ]
    )

    page = query_radar(session, now=now, hours=48, limit=50)
    assert len(page.items) == 1
    item = page.items[0]
    assert item.id == sig_id
    assert item.title_english == "Cholera in Luanda"
    assert len(item.brief) == 5
    assert item.event_context_status == EventContextStatus.NONE
    assert item.event is None
    assert item.location is None
    assert item.source.url == "https://publisher.com/article/1"


def test_query_radar_assembly_attached_event() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    sig_id = uuid4()
    sig_row = FakeSignalRow(id=sig_id)
    ev_row = FakeEventRow(
        signal_id=sig_id,
        public_id="EVT-2026-001",
        verification_status=VerificationStatus.OFFICIALLY_CONFIRMED,
        early_signal_score=0.88,
        evidence_score=0.91,
    )

    session = FakeSession(
        [
            FakeResult([sig_row]),
            FakeResult([]),
            FakeResult([ev_row]),
        ]
    )

    page = query_radar(session, now=now, hours=48, limit=50)
    assert len(page.items) == 1
    item = page.items[0]
    assert item.event_context_status == EventContextStatus.ATTACHED
    assert item.event is not None
    assert item.event.public_id == "EVT-2026-001"
    assert item.event.verification_status == VerificationStatus.OFFICIALLY_CONFIRMED
    assert item.event.early_signal_score == 0.88
    assert item.event.evidence_score == 0.91


def test_query_radar_assembly_ambiguous_events() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    sig_id = uuid4()
    sig_row = FakeSignalRow(id=sig_id)
    ev1 = FakeEventRow(signal_id=sig_id, public_id="EVT-001")
    ev2 = FakeEventRow(signal_id=sig_id, public_id="EVT-002")

    session = FakeSession(
        [
            FakeResult([sig_row]),
            FakeResult([]),
            FakeResult([ev1, ev2]),
        ]
    )

    page = query_radar(session, now=now, hours=48, limit=50)
    assert len(page.items) == 1
    item = page.items[0]
    assert item.event_context_status == EventContextStatus.AMBIGUOUS
    assert item.event is None


def test_query_radar_assembly_malformed_extraction_is_omitted() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    sig1 = FakeSignalRow(
        id=uuid4(),
        ai_extraction={
            "extraction_schema_version": 2,
            "title_english": "",  # Blank title: malformed!
            "brief": [],
        },
    )
    sig2 = FakeSignalRow(id=uuid4())

    session = FakeSession(
        [
            FakeResult([sig1, sig2]),
            FakeResult([]),
            FakeResult([]),
        ]
    )

    page = query_radar(session, now=now, hours=48, limit=50)
    assert len(page.items) == 1
    assert page.items[0].id == sig2.id


def test_query_pipeline_runs_ordering_and_limit() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    session = FakeSession()

    page = query_pipeline_runs(session, now=now, stale_after_minutes=60, limit=20)
    assert page.items == ()
    assert page.limit == 20

    statement = str(session.executed[0])
    assert "FROM pipeline_runs" in statement
    assert "ORDER BY pipeline_runs.started_at DESC" in statement
    assert "LIMIT" in statement


def test_query_pipeline_runs_normalizes_stage_counts_and_backlog() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    run_id = uuid4()
    run = PipelineRun(
        chain=PipelineChain.DAILY,
        trigger=PipelineTrigger.SCHEDULED,
        status=PipelineRunStatus.SUCCEEDED,
        started_at=now,
        finished_at=now,
        window_start=None,
        window_end=None,
        stage_counts={
            "extract": {"extracted": 5, "invalid_count": "three", "bad_bool": True},
            "invalid_stage": "not_a_dict",
        },
        backlog={"extracted": 10, "bad_val": None, "bool_val": False},
        failed_stages=[],
    )
    run.id = run_id

    session = FakeSession([FakeResult([run])])
    page = query_pipeline_runs(session, now=now, stale_after_minutes=60, limit=20)
    assert len(page.items) == 1
    item = page.items[0]
    assert item.stage_counts == {"extract": {"extracted": 5}}
    assert item.backlog == {"extracted": 10}
    assert item.failures == ()
    assert item.is_stale is False


def test_query_pipeline_runs_compatibility_with_legacy_and_new_failures() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    run = PipelineRun(
        chain=PipelineChain.DAILY,
        trigger=PipelineTrigger.SCHEDULED,
        status=PipelineRunStatus.FAILED,
        started_at=now,
        finished_at=now,
        window_start=None,
        window_end=None,
        stage_counts={},
        backlog={},
        failed_stages=[
            "extract",  # Legacy string
            {"stage": "geocode", "error": "TimeoutError"},  # New object
            {"stage": "unknown_future_stage", "error": "Something"},  # Unknown stage: ignore
            12345,  # Malformed: ignore
        ],
    )
    run.id = uuid4()

    session = FakeSession([FakeResult([run])])
    page = query_pipeline_runs(session, now=now, stale_after_minutes=60, limit=20)
    assert len(page.items) == 1
    failures = page.items[0].failures
    assert len(failures) == 2
    assert failures[0] == PipelineFailure(stage=StageName.EXTRACT, error=None)
    assert failures[1] == PipelineFailure(stage=StageName.GEOCODE, error="TimeoutError")


def test_query_pipeline_runs_is_stale_flag() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

    # 1. Running and started 3 hours ago with stale_after_minutes=60 -> stale!
    stale_run = PipelineRun(
        chain=PipelineChain.DAILY,
        trigger=PipelineTrigger.SCHEDULED,
        status=PipelineRunStatus.RUNNING,
        started_at=datetime(2026, 8, 28, 9, 0, tzinfo=UTC),
        finished_at=None,
        window_start=None,
        window_end=None,
        stage_counts={},
        backlog={},
        failed_stages=[],
    )
    stale_run.id = uuid4()

    # 2. Running and started 30 mins ago -> not stale
    fresh_run = PipelineRun(
        chain=PipelineChain.DAILY,
        trigger=PipelineTrigger.SCHEDULED,
        status=PipelineRunStatus.RUNNING,
        started_at=datetime(2026, 8, 28, 11, 30, tzinfo=UTC),
        finished_at=None,
        window_start=None,
        window_end=None,
        stage_counts={},
        backlog={},
        failed_stages=[],
    )
    fresh_run.id = uuid4()

    # 3. Finished run from 5 hours ago -> not stale
    finished_run = PipelineRun(
        chain=PipelineChain.DAILY,
        trigger=PipelineTrigger.SCHEDULED,
        status=PipelineRunStatus.SUCCEEDED,
        started_at=datetime(2026, 8, 28, 7, 0, tzinfo=UTC),
        finished_at=datetime(2026, 8, 28, 7, 10, tzinfo=UTC),
        window_start=None,
        window_end=None,
        stage_counts={},
        backlog={},
        failed_stages=[],
    )
    finished_run.id = uuid4()

    session = FakeSession([FakeResult([stale_run, fresh_run, finished_run])])
    page = query_pipeline_runs(session, now=now, stale_after_minutes=60, limit=20)
    assert len(page.items) == 3
    assert page.items[0].is_stale is True
    assert page.items[1].is_stale is False
    assert page.items[2].is_stale is False


def test_query_pipeline_runs_sanitizes_unsafe_error_strings_to_none() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    run = PipelineRun(
        chain=PipelineChain.DAILY,
        trigger=PipelineTrigger.SCHEDULED,
        status=PipelineRunStatus.FAILED,
        started_at=now,
        finished_at=now,
        window_start=None,
        window_end=None,
        stage_counts={},
        backlog={},
        failed_stages=[
            {"stage": "extract", "error": "TimeoutError"},  # Valid identifier: preserved
            {
                "stage": "extract",
                "error": "https://api.openrouter.ai/v1/chat",
            },  # URL: converted to None
            {
                "stage": "dedupe",
                "error": "Failed to connect to db at postgresql://user:pass@host/db",
            },  # Secret/Message: converted to None
            {
                "stage": "geocode",
                "error": "Traceback (most recent call last):\n  File 'app.py'",
            },  # Traceback: converted to None
            {
                "stage": "match",
                "error": "Error: 500 Server Error",
            },  # Message with spaces/colon: converted to None
            {"stage": "ingest_who", "error": "OperationalError"},  # Valid identifier: preserved
        ],
    )
    run.id = uuid4()

    session = FakeSession([FakeResult([run])])
    page = query_pipeline_runs(session, now=now, stale_after_minutes=60, limit=20)
    assert len(page.items) == 1
    failures = page.items[0].failures
    assert len(failures) == 6
    assert failures[0] == PipelineFailure(stage=StageName.EXTRACT, error="TimeoutError")
    assert failures[1] == PipelineFailure(stage=StageName.EXTRACT, error=None)
    assert failures[2] == PipelineFailure(stage=StageName.DEDUPE, error=None)
    assert failures[3] == PipelineFailure(stage=StageName.GEOCODE, error=None)
    assert failures[4] == PipelineFailure(stage=StageName.MATCH, error=None)
    assert failures[5] == PipelineFailure(stage=StageName.INGEST_WHO, error="OperationalError")


def test_query_radar_pagination_skips_malformed_without_consuming_limit() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    sig1 = FakeSignalRow(
        id=uuid4(),
        ai_extraction={"extraction_schema_version": 2, "title_english": "", "brief": []},
    )
    sig2 = FakeSignalRow(id=uuid4())
    sig3 = FakeSignalRow(id=uuid4())

    session = FakeSession(
        [
            FakeResult([sig1, sig2, sig3]),
            FakeResult([]),
            FakeResult([]),
        ]
    )

    page = query_radar(session, now=now, hours=48, limit=2)
    assert len(page.items) == 2
    assert page.items[0].id == sig2.id
    assert page.items[1].id == sig3.id


def test_query_radar_excludes_signal_with_mismatched_content_hash(caplog: Any) -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    corrupted_sig = FakeSignalRow(
        id=uuid4(),
        title="Pennsylvania reports first 2 measles deaths",
        raw_text="Health officials in Luanda, Angola reported 50 confirmed cases of cholera.",
        content_hash="0000000000000000000000000000000000000000000000000000000000000000",
    )

    session = FakeSession(
        [
            FakeResult([corrupted_sig]),
            FakeResult([]),
            FakeResult([]),
        ]
    )

    with caplog.at_level("WARNING"):
        page = query_radar(session, now=now, hours=48, limit=50)

    assert len(page.items) == 0
    assert str(corrupted_sig.id) in caplog.text
    assert "failed content hash integrity" in caplog.text


def test_query_radar_pagination_scans_past_mismatched_content_hash() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    corrupted_sig = FakeSignalRow(
        id=uuid4(),
        title="Pennsylvania measles deaths",
        raw_text="Luanda cholera body",
        content_hash="badhash000000000000000000000000000000000000000000000000000000000",
    )
    valid_sig1 = FakeSignalRow(id=uuid4())
    valid_sig2 = FakeSignalRow(id=uuid4())

    session = FakeSession(
        [
            FakeResult([corrupted_sig, valid_sig1, valid_sig2]),
            FakeResult([]),
            FakeResult([]),
        ]
    )

    page = query_radar(session, now=now, hours=48, limit=2)
    assert len(page.items) == 2
    assert page.items[0].id == valid_sig1.id
    assert page.items[1].id == valid_sig2.id


def test_query_radar_statement_selects_integrity_fields() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    session = FakeSession()

    query_radar(session, now=now, hours=48, limit=50)
    statement = str(session.executed[0])
    assert "signals.title" in statement
    assert "signals.raw_text" in statement
    assert "signals.content_hash" in statement
