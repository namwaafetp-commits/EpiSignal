from datetime import UTC, datetime, timedelta
from uuid import uuid4

from episignal_backend.db.types import CredibilityTier, LocationRole, Precision
from episignal_backend.events.documents import (
    CandidateEvent,
    LocationForMatching,
    SignalForMatching,
    StoryCluster,
)
from episignal_backend.events.match import (
    DEFAULT_MATCH_WEIGHTS,
    match_score,
)


def _make_cluster(
    disease_id,
    loc,
    published_at,
) -> StoryCluster:
    sig = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=published_at,
        first_seen_at=published_at,
        locations=(loc,),
    )
    return StoryCluster(signals=(sig,))


def test_match_score_identical_disease_place_recent_scores_near_top():
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
    cluster = _make_cluster(disease_id, loc, now)
    candidate = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(loc,),
        first_signal_at=now - timedelta(days=2),
        last_updated_at=now - timedelta(days=1),
    )

    score = match_score(cluster, candidate)
    assert 0.85 <= score <= 1.0


def test_match_score_different_country_scores_at_or_near_zero():
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc_cd = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )
    loc_ug = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="UG",
        admin1="Central",
        place_name="Kampala",
        latitude=0.34,
        longitude=32.58,
    )
    cluster = _make_cluster(disease_id, loc_cd, now)
    candidate = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(loc_ug,),
        first_signal_at=now - timedelta(days=2),
        last_updated_at=now - timedelta(days=1),
    )

    score = match_score(cluster, candidate)
    assert score == 0.0


def test_match_score_different_disease_scores_zero():
    now = datetime.now(UTC)
    disease_1 = uuid4()
    disease_2 = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )
    cluster = _make_cluster(disease_1, loc, now)
    candidate = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_2,
        locations=(loc,),
        first_signal_at=now - timedelta(days=2),
        last_updated_at=now - timedelta(days=1),
    )

    score = match_score(cluster, candidate)
    assert score == 0.0


def test_match_score_country_precision_only_cannot_reach_accept_threshold():
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc_country = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="CD",
        latitude=-4.03,
        longitude=21.75,
    )
    cluster = _make_cluster(disease_id, loc_country, now)
    candidate = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(loc_country,),
        first_signal_at=now - timedelta(days=2),
        last_updated_at=now - timedelta(days=1),
    )

    score = match_score(cluster, candidate)
    # With default threshold 0.70, country precision alone must not reach it
    assert score < 0.70
    assert 0.0 < score <= 0.65


def test_match_score_bounds_and_weights():
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )
    cluster = _make_cluster(disease_id, loc, now)
    candidate = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(loc,),
        first_signal_at=now - timedelta(days=2),
        last_updated_at=now - timedelta(days=1),
    )

    score = match_score(cluster, candidate, weights=DEFAULT_MATCH_WEIGHTS)
    assert 0.0 <= score <= 1.0
