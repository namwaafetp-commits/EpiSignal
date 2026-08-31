from datetime import UTC, datetime, timedelta
from uuid import uuid4

from episignal_backend.db.types import CredibilityTier, LocationRole, Precision
from episignal_backend.events.documents import (
    CandidateEvent,
    LocationForMatching,
    MatchAction,
    MatchRejection,
    SignalForMatching,
    StoryCluster,
)
from episignal_backend.events.match import (
    DEFAULT_MATCH_WEIGHTS,
    decide,
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
    # With default threshold 0.75, country precision alone must not reach it
    assert score < 0.75
    assert 0.0 < score <= 0.65


def test_same_disease_same_country_can_attach_at_the_lean_mvp_threshold():
    now = datetime.now(UTC)
    disease_id = uuid4()
    country = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="CD",
        latitude=-4.03,
        longitude=21.75,
    )
    cluster = _make_cluster(disease_id, country, now)
    candidate = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(country,),
        first_signal_at=now - timedelta(days=1),
        last_updated_at=now,
    )

    decision = decide(
        cluster,
        [candidate],
        threshold=0.60,
    )

    assert decision.action is MatchAction.ATTACH
    assert decision.event_id == candidate.event_id


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


def test_decide_attach_when_exactly_one_candidate_qualifies():

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

    event_1_id = uuid4()
    candidate_1 = CandidateEvent(
        event_id=event_1_id,
        disease_id=disease_id,
        locations=(loc,),
        first_signal_at=now - timedelta(days=2),
        last_updated_at=now - timedelta(days=1),
    )
    candidate_2 = CandidateEvent(
        event_id=uuid4(),
        disease_id=uuid4(),  # Different disease -> score 0.0
        locations=(loc,),
        first_signal_at=now - timedelta(days=2),
        last_updated_at=now - timedelta(days=1),
    )

    decision = decide(cluster, [candidate_1, candidate_2], threshold=0.70)
    assert decision.action == MatchAction.ATTACH
    assert decision.event_id == event_1_id
    assert decision.match_score is not None
    assert decision.match_score >= 0.70


def test_decide_create_when_zero_candidates_qualify():

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
        disease_id=uuid4(),  # Different disease -> score 0.0
        locations=(loc,),
        first_signal_at=now - timedelta(days=2),
        last_updated_at=now - timedelta(days=1),
    )

    decision = decide(cluster, [candidate], threshold=0.70)
    assert decision.action == MatchAction.CREATE
    assert decision.event_id is None
    assert decision.match_score is None


def test_decide_refuse_when_two_or_more_candidates_qualify():

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

    candidate_1 = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(loc,),
        first_signal_at=now - timedelta(days=2),
        last_updated_at=now - timedelta(days=1),
    )
    candidate_2 = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(loc,),
        first_signal_at=now - timedelta(days=3),
        last_updated_at=now - timedelta(days=1),
    )

    # Both candidates have score >= 0.70
    decision = decide(cluster, [candidate_1, candidate_2], threshold=0.70)
    assert decision.action == MatchAction.REFUSE
    assert decision.event_id is None
    assert decision.match_score is None
    # Verify candidate_scores has both scores
    assert len(decision.candidate_scores) == 2


def test_decide_candidate_exactly_at_threshold_qualifies():

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
    event_id = uuid4()
    candidate = CandidateEvent(
        event_id=event_id,
        disease_id=disease_id,
        locations=(loc,),
        first_signal_at=now - timedelta(days=2),
        last_updated_at=now - timedelta(days=1),
    )

    actual_score = match_score(cluster, candidate)
    decision = decide(cluster, [candidate], threshold=actual_score)
    assert decision.action == MatchAction.ATTACH
    assert decision.event_id == event_id
    assert decision.match_score == actual_score


def _safety_fixtures() -> tuple[StoryCluster, CandidateEvent, CandidateEvent, CandidateEvent]:
    now = datetime.now(UTC)
    dengue_id = uuid4()
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
    cluster = _make_cluster(dengue_id, chiang_mai, now)

    def event(disease_id, location) -> CandidateEvent:
        return CandidateEvent(
            event_id=uuid4(),
            disease_id=disease_id,
            locations=(location,),
            first_signal_at=now - timedelta(days=2),
            last_updated_at=now - timedelta(days=1),
        )

    return (
        cluster,
        event(dengue_id, chiang_mai_admin1),
        event(dengue_id, phuket_admin1),
        event(uuid4(), chiang_mai_admin1),
    )


def test_conflicting_admin1_is_refused_before_similarity_is_consulted() -> None:
    cluster, _, phuket_event, _ = _safety_fixtures()
    calls = []

    decision = decide(
        cluster,
        [phuket_event],
        similarity_for=lambda _, event: calls.append(event.event_id) or 0.99,
        threshold=0.80,
    )

    assert decision.action is MatchAction.CREATE
    assert decision.candidate_rejections[phuket_event.event_id] is MatchRejection.CONFLICTING_ADMIN1
    assert calls == []


def test_similarity_cannot_veto_a_deterministic_match() -> None:
    cluster, chiang_mai_event, _, _ = _safety_fixtures()

    decision = decide(
        cluster,
        [chiang_mai_event],
        similarity_for=lambda _cluster, _event: 0.10,
        threshold=0.80,
    )

    assert decision.action is MatchAction.ATTACH


def test_similarity_raises_the_score_of_a_permitted_pair() -> None:
    cluster, chiang_mai_event, _, _ = _safety_fixtures()

    low = decide(
        cluster,
        [chiang_mai_event],
        similarity_for=lambda _cluster, _event: 0.10,
        threshold=0.80,
    )
    high = decide(
        cluster,
        [chiang_mai_event],
        similarity_for=lambda _cluster, _event: 0.95,
        threshold=0.80,
    )

    assert (
        high.candidate_scores[chiang_mai_event.event_id]
        > low.candidate_scores[chiang_mai_event.event_id]
    )


def test_a_missing_embedding_falls_back_to_the_deterministic_score() -> None:
    cluster, chiang_mai_event, _, _ = _safety_fixtures()

    decision = decide(cluster, [chiang_mai_event], threshold=0.80)

    assert decision.action is MatchAction.ATTACH
    assert decision.candidate_rejections[chiang_mai_event.event_id] is None


def test_a_different_disease_is_refused_with_its_own_reason() -> None:
    cluster, _, _, measles_event = _safety_fixtures()
    calls = []

    decision = decide(
        cluster,
        [measles_event],
        similarity_for=lambda _, event: calls.append(event.event_id) or 0.99,
        threshold=0.80,
    )

    assert decision.action is MatchAction.CREATE
    assert decision.candidate_rejections[measles_event.event_id] is MatchRejection.DISEASE_MISMATCH
    assert calls == []
