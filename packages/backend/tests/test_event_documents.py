from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from episignal_backend.ai.schema import Extraction
from episignal_backend.db.types import CredibilityTier, LocationRole, Precision, SignalType
from episignal_backend.events.documents import (
    CandidateEvent,
    LocationForMatching,
    MatchAction,
    MatchDecision,
    ScoreBreakdown,
    SignalForMatching,
    StoryCluster,
)
from pydantic import ValidationError


def test_location_for_matching_valid():
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
    assert loc.precision == Precision.PLACE
    assert loc.country_code == "CD"
    assert loc.latitude == 0.49


def test_location_for_matching_unresolved_allows_null_coordinates():
    loc = LocationForMatching(
        location_role=LocationRole.REPORTING,
        precision=Precision.UNRESOLVED,
        place_name="Unknown Village",
        latitude=None,
        longitude=None,
    )
    assert loc.precision == Precision.UNRESOLVED
    assert loc.latitude is None
    assert loc.longitude is None


def test_location_for_matching_rejects_null_coords_when_not_unresolved():
    with pytest.raises(ValidationError):
        LocationForMatching(
            location_role=LocationRole.PRIMARY,
            precision=Precision.PLACE,
            country_code="CD",
            latitude=None,
            longitude=29.47,
        )


def test_signal_for_matching_requires_signal_id():
    with pytest.raises(ValidationError):
        SignalForMatching(
            signal_id=None,  # type: ignore[arg-type]
            source_id=uuid4(),
            source_is_official=False,
            credibility_tier=CredibilityTier.MEDIUM,
            first_seen_at=datetime.now(UTC),
        )


def test_signal_for_matching_valid():
    sig_id = uuid4()
    disease_id = uuid4()
    src_id = uuid4()
    now = datetime.now(UTC)
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        latitude=0.49,
        longitude=29.47,
    )
    extraction = Extraction(
        signal_type=SignalType.OUTBREAK_REPORT,
        summary="Ebola in Beni",
        confidence=0.9,
    )
    sig = SignalForMatching(
        signal_id=sig_id,
        disease_id=disease_id,
        source_id=src_id,
        source_is_official=True,
        credibility_tier=CredibilityTier.OFFICIAL,
        published_at=now,
        first_seen_at=now,
        locations=(loc,),
        extraction=extraction,
    )
    assert sig.signal_id == sig_id
    assert sig.disease_id == disease_id
    assert sig.source_is_official is True
    assert len(sig.locations) == 1


def test_story_cluster_requires_non_empty_signals():
    with pytest.raises(ValidationError):
        StoryCluster(signals=())


def test_story_cluster_properties():
    now = datetime.now(UTC)
    sig_id = uuid4()
    disease_id = uuid4()
    loc1 = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.ADMIN1,
        country_code="CD",
        admin1="North Kivu",
        latitude=0.5,
        longitude=29.5,
    )
    loc2 = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )
    sig1 = SignalForMatching(
        signal_id=sig_id,
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now - timedelta(days=2),
        first_seen_at=now - timedelta(days=2),
        locations=(loc1,),
    )
    sig2 = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=True,
        credibility_tier=CredibilityTier.OFFICIAL,
        published_at=now,
        first_seen_at=now,
        locations=(loc2,),
    )
    cluster = StoryCluster(signals=(sig1, sig2))
    assert cluster.disease_id == disease_id
    # Representative location should prefer higher precision primary location (PLACE over ADMIN1)
    rep = cluster.representative_location
    assert rep is not None
    assert rep.precision == Precision.PLACE
    assert rep.place_name == "Beni"
    start, end = cluster.span
    assert start == now - timedelta(days=2)
    assert end == now


def test_candidate_event():
    event_id = uuid4()
    disease_id = uuid4()
    now = datetime.now(UTC)
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        latitude=0.49,
        longitude=29.47,
    )
    cand = CandidateEvent(
        event_id=event_id,
        disease_id=disease_id,
        locations=(loc,),
        first_signal_at=now - timedelta(days=5),
        last_updated_at=now,
    )
    assert cand.event_id == event_id
    assert cand.disease_id == disease_id


def test_match_decision_attach_validation():
    event_id = uuid4()
    decision = MatchDecision(
        action=MatchAction.ATTACH,
        event_id=event_id,
        match_score=0.85,
    )
    assert decision.action == MatchAction.ATTACH
    assert decision.event_id == event_id
    assert decision.match_score == 0.85

    # Attach without event_id must fail
    with pytest.raises(ValidationError):
        MatchDecision(
            action=MatchAction.ATTACH,
            event_id=None,
            match_score=0.85,
        )

    # Attach without match_score must fail
    with pytest.raises(ValidationError):
        MatchDecision(
            action=MatchAction.ATTACH,
            event_id=event_id,
            match_score=None,
        )


def test_match_decision_create_and_refuse_validation():
    create = MatchDecision(action=MatchAction.CREATE)
    assert create.action == MatchAction.CREATE
    assert create.event_id is None
    assert create.match_score is None

    refuse = MatchDecision(action=MatchAction.REFUSE)
    assert refuse.action == MatchAction.REFUSE
    assert refuse.event_id is None
    assert refuse.match_score is None

    # Create with event_id must fail
    with pytest.raises(ValidationError):
        MatchDecision(
            action=MatchAction.CREATE,
            event_id=uuid4(),
        )


def test_score_breakdown():
    breakdown = ScoreBreakdown(
        components={"recency": 0.8, "velocity": 0.6},
        total=0.7,
    )
    assert breakdown.total == 0.7
    assert breakdown.components["recency"] == 0.8

    # Score breakdown outside 0-1 must fail
    with pytest.raises(ValidationError):
        ScoreBreakdown(
            components={"recency": 1.5},
            total=1.2,
        )
