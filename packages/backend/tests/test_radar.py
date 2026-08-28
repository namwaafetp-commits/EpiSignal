from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
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
from episignal_backend.models import SignalLocation
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
