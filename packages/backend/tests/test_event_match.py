"""Exact deterministic event matching tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from episignal_backend.db.types import CredibilityTier, LocationRole, Precision
from episignal_backend.events.cluster import compatible
from episignal_backend.events.documents import (
    CandidateEvent,
    LocationForMatching,
    MatchAction,
    SignalForMatching,
    StoryCluster,
)
from episignal_backend.events.match import decide, match_score


def loc(town: str | None, country: str) -> LocationForMatching:
    return LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE if town else Precision.COUNTRY,
        country_code=country,
        place_name=town,
    )


def signal(
    disease: str,
    locations: tuple[LocationForMatching, ...],
    at: datetime | None = None,
    *,
    disease_id: UUID | None = None,
) -> SignalForMatching:
    moment = at or datetime(2026, 9, 2, tzinfo=UTC)
    return SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        disease_text=disease,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=moment,
        first_seen_at=moment,
        locations=locations,
    )


def candidate(
    disease: str,
    locations: tuple[LocationForMatching, ...],
    at: datetime | None = None,
    *,
    disease_id: UUID | None = None,
) -> CandidateEvent:
    moment = at or datetime(2026, 9, 2, tzinfo=UTC)
    return CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        disease_text=disease,
        locations=locations,
        first_signal_at=moment,
        last_updated_at=moment,
    )


def test_exact_disease_and_location_attach() -> None:
    cluster = StoryCluster(signals=(signal(" dengue ", (loc("Cebu", "PH"),)),))
    existing = candidate("dengue", (loc(" Cebu ", "PH"),))
    decision = decide(cluster, (existing,), threshold=0.5)
    assert decision.action is MatchAction.ATTACH
    assert match_score(cluster, existing) > 0.5


def test_available_disease_ids_are_the_exact_grouping_identity() -> None:
    location = (loc("Cebu", "PH"),)
    canonical_id = uuid4()
    cluster = StoryCluster(signals=(signal("dengue", location, disease_id=canonical_id),))
    same_id_different_text = candidate("Dengue virus", location, disease_id=canonical_id)
    different_id_same_text = candidate("dengue", location, disease_id=uuid4())

    assert compatible(cluster.signals[0], signal("other label", location, disease_id=canonical_id))
    assert decide(cluster, (same_id_different_text,), threshold=0.5).action is MatchAction.ATTACH
    assert decide(cluster, (different_id_same_text,), threshold=0.5).action is MatchAction.CREATE


def test_country_only_matches_same_country_but_not_local_place() -> None:
    country = StoryCluster(signals=(signal("dengue", (loc(None, "PH"),)),))
    local = candidate("dengue", (loc("Cebu", "PH"),))
    same_country = candidate("dengue", (loc(None, "PH"),))
    assert decide(country, (local,), threshold=0.5).action is MatchAction.CREATE
    assert decide(country, (same_country,), threshold=0.5).action is MatchAction.ATTACH


def test_different_towns_or_diseases_stay_separate() -> None:
    cluster = StoryCluster(signals=(signal("dengue", (loc("Cebu", "PH"),)),))
    other_town = candidate("dengue", (loc("Manila", "PH"),))
    other_disease = candidate("measles", (loc("Cebu", "PH"),))
    assert decide(cluster, (other_town,), threshold=0.5).action is MatchAction.CREATE
    assert decide(cluster, (other_disease,), threshold=0.5).action is MatchAction.CREATE


def test_multiple_locations_match_on_any_exact_overlap() -> None:
    left = signal("dengue", (loc("Cebu", "PH"), loc("Dhaka", "BD")))
    right = signal("dengue", (loc("Dhaka", "BD"),))
    assert compatible(left, right)


def test_time_window_and_ambiguous_candidates_are_conservative() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    cluster = StoryCluster(signals=(signal("dengue", (loc("Cebu", "PH"),), now),))
    old = candidate("dengue", (loc("Cebu", "PH"),), now - timedelta(days=100))
    assert decide(cluster, (old,), threshold=0.5).action is MatchAction.CREATE

    first = candidate("dengue", (loc("Cebu", "PH"),))
    second = candidate("dengue", (loc("Cebu", "PH"),))
    assert decide(cluster, (first, second), threshold=0.5).action is MatchAction.REFUSE
