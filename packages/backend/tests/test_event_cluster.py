"""Conservative exact disease/location/time grouping tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from episignal_backend.db.types import CredibilityTier, LocationRole, Precision
from episignal_backend.events.cluster import (
    build_clusters,
    compatible,
    spatially_compatible,
    temporally_compatible,
)
from episignal_backend.events.documents import LocationForMatching, SignalForMatching


def loc(town: str | None, country: str) -> LocationForMatching:
    return LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE if town else Precision.COUNTRY,
        country_code=country,
        place_name=town,
    )


def signal(
    disease: str | None, locations: tuple[LocationForMatching, ...], at: datetime | None = None
) -> SignalForMatching:
    moment = at or datetime(2026, 9, 2, tzinfo=UTC)
    return SignalForMatching(
        signal_id=uuid4(),
        disease_text=disease,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=moment,
        first_seen_at=moment,
        locations=locations,
    )


def test_exact_normalized_disease_and_location_overlap_groups() -> None:
    assert compatible(
        signal(" dengue ", (loc("Cebu", "PH"),)), signal("dengue", (loc(" cebu ", "PH"),))
    )


def test_country_only_and_local_place_do_not_automatically_merge() -> None:
    assert not spatially_compatible(loc(None, "PH"), loc("Cebu", "PH"))
    assert spatially_compatible(loc(None, "PH"), loc(None, "PH"))


def test_partial_location_overlap_does_not_establish_event_identity() -> None:
    left = signal("dengue", (loc("Cebu", "PH"), loc("Dhaka", "BD")))
    right = signal("dengue", (loc("Dhaka", "BD"),))
    assert not compatible(left, right)


def test_different_disease_or_town_stays_separate() -> None:
    base = signal("dengue", (loc("Cebu", "PH"),))
    assert not compatible(base, signal("measles", (loc("Cebu", "PH"),)))
    assert not compatible(base, signal("dengue", (loc("Manila", "PH"),)))


def test_temporal_window_is_enforced_and_clusters_are_not_transitive_bridges() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    first = signal("dengue", (loc("Cebu", "PH"),), now)
    late = signal("dengue", (loc("Cebu", "PH"),), now + timedelta(days=15))
    assert not temporally_compatible(first, late)
    clusters, unclusterable = build_clusters((first, late))
    assert len(clusters) == 2 and not unclusterable


def test_shared_reporting_city_cannot_join_distinct_primary_places() -> None:
    first = signal("measles", (loc("Indiana", "US"),))
    second = signal("measles", (loc("New York", "US"),))
    reporting = loc("Washington", "US").model_copy(update={"location_role": LocationRole.REPORTING})
    first = first.model_copy(update={"locations": (*first.locations, reporting)})
    second = second.model_copy(update={"locations": (*second.locations, reporting)})
    clusters, _ = build_clusters((first, second))
    assert len(clusters) == 2


def test_multi_location_bridge_cannot_join_conflicting_primary_sets() -> None:
    first = signal("measles", (loc("Indiana", "US"),))
    second = signal("measles", (loc("New York", "US"),))
    bridge = signal("measles", (*first.locations, *second.locations))
    clusters, _ = build_clusters((first, bridge, second))
    assert len(clusters) == 3


def test_identical_multi_location_reporting_keeps_one_event_identity() -> None:
    places = (loc("Cebu", "PH"), loc("Dhaka", "BD"))
    left = signal("dengue", places)
    right = signal("dengue", tuple(reversed(places)))
    assert compatible(left, right)
