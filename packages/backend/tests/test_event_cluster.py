from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from episignal_backend.db.types import CredibilityTier, LocationRole, Precision
from episignal_backend.events.cluster import (
    build_clusters,
    compatible,
    precision_weight,
    spatially_compatible,
    temporally_compatible,
)
from episignal_backend.events.documents import LocationForMatching, SignalForMatching


def _unknown_disease_signal(text: str, *, now: datetime) -> SignalForMatching:
    location = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="US",
    )
    return SignalForMatching(
        signal_id=uuid4(),
        disease_text=text,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now,
        first_seen_at=now,
        locations=(location,),
    )


def test_unknown_disease_text_groups_by_exact_normalized_text() -> None:
    now = datetime.now(UTC)
    first = _unknown_disease_signal("Meningococcal disease", now=now)
    same = _unknown_disease_signal(" meningococcal   disease ", now=now)
    different = _unknown_disease_signal("Lassa fever", now=now)

    clusters, unclusterable = build_clusters([first, same, different])

    assert len(unclusterable) == 0
    assert {cluster.disease_identity for cluster in clusters} == {
        "text:meningococcal disease",
        "text:lassa fever",
    }
    assert sorted(len(cluster.signals) for cluster in clusters) == [1, 2]


def test_precision_weights():
    assert precision_weight(Precision.PLACE) == 1.0
    assert precision_weight(Precision.ADMIN2) == 0.75
    assert precision_weight(Precision.ADMIN1) == 0.5
    assert precision_weight(Precision.COUNTRY) == 0.25
    assert precision_weight(Precision.UNRESOLVED) == 0.0


def test_precision_weights_strictly_decreasing():
    precisions = [
        Precision.PLACE,
        Precision.ADMIN2,
        Precision.ADMIN1,
        Precision.COUNTRY,
        Precision.UNRESOLVED,
    ]
    weights = [precision_weight(p) for p in precisions]
    for i in range(len(weights) - 1):
        assert weights[i] > weights[i + 1]


def test_spatially_compatible_place_precision_distance():
    beni = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        admin2="Beni",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )
    near_beni = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        admin2="Beni",
        place_name="Beni Suburb",
        latitude=0.53,
        longitude=29.47,
    )
    kinshasa = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="Kinshasa",
        place_name="Kinshasa",
        latitude=-4.32,
        longitude=15.31,
    )

    assert spatially_compatible(beni, near_beni, distance_km=50) is True
    assert spatially_compatible(beni, kinshasa, distance_km=50) is False


def test_spatially_compatible_admin1_precision_compares_codes_never_distance():
    place_in_kivu = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        latitude=0.50,
        longitude=29.50,
    )
    kivu_province = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.ADMIN1,
        country_code="CD",
        admin1="North Kivu",
        latitude=0.50,
        longitude=29.50,
    )
    ituri_province_close = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.ADMIN1,
        country_code="CD",
        admin1="Ituri",
        latitude=0.51,  # ~1 km away
        longitude=29.50,
    )

    assert spatially_compatible(place_in_kivu, kivu_province, distance_km=50) is True
    assert spatially_compatible(place_in_kivu, ituri_province_close, distance_km=50) is False


def test_spatially_compatible_country_precision_compares_country_code():
    place_in_cd = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        latitude=0.50,
        longitude=29.50,
    )
    cd_country = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="CD",
        latitude=-4.03,
        longitude=21.75,
    )
    ug_country = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="UG",
        latitude=1.37,
        longitude=32.29,
    )

    assert spatially_compatible(place_in_cd, cd_country, distance_km=50) is True
    assert spatially_compatible(place_in_cd, ug_country, distance_km=50) is False


def test_spatially_compatible_unresolved_returns_false_and_never_raises():
    unresolved = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.UNRESOLVED,
        place_name="Nowhere",
        latitude=None,
        longitude=None,
    )
    place = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        latitude=0.50,
        longitude=29.50,
    )

    assert spatially_compatible(unresolved, place, distance_km=50) is False
    assert spatially_compatible(place, unresolved, distance_km=50) is False
    assert spatially_compatible(unresolved, unresolved, distance_km=50) is False


def test_spatially_compatible_different_country_codes_always_fail():
    goma = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        place_name="Goma",
        latitude=-1.67,
        longitude=29.23,
    )
    gisenyi = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="RW",
        place_name="Gisenyi",
        latitude=-1.70,
        longitude=29.26,
    )

    assert spatially_compatible(goma, gisenyi, distance_km=50) is False


def test_temporally_compatible_within_and_outside_window():
    now = datetime.now(UTC)
    sig1 = SignalForMatching(
        signal_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now,
        first_seen_at=now,
    )
    sig2_inside = SignalForMatching(
        signal_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now - timedelta(days=10),
        first_seen_at=now - timedelta(days=10),
    )
    sig3_outside = SignalForMatching(
        signal_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now - timedelta(days=20),
        first_seen_at=now - timedelta(days=20),
    )

    assert temporally_compatible(sig1, sig2_inside, window_days=14) is True
    assert temporally_compatible(sig2_inside, sig1, window_days=14) is True
    assert temporally_compatible(sig1, sig3_outside, window_days=14) is False
    assert temporally_compatible(sig3_outside, sig1, window_days=14) is False


def test_temporally_compatible_fallback_to_first_seen_at():
    now = datetime.now(UTC)
    sig_with_pub = SignalForMatching(
        signal_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now,
        first_seen_at=now,
    )
    sig_no_pub = SignalForMatching(
        signal_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=None,
        first_seen_at=now - timedelta(days=3),
    )

    assert temporally_compatible(sig_with_pub, sig_no_pub, window_days=14) is True
    assert temporally_compatible(sig_no_pub, sig_with_pub, window_days=14) is True


def test_temporally_compatible_rejects_naive_datetimes():
    naive_dt = datetime(2026, 8, 28, 10, 0, 0)
    aware_dt = datetime(2026, 8, 28, 10, 0, 0, tzinfo=UTC)

    sig_aware = SignalForMatching(
        signal_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=aware_dt,
        first_seen_at=aware_dt,
    )

    class MockSignal:
        published_at = naive_dt
        first_seen_at = naive_dt

    with pytest.raises(ValueError, match="Timezone-aware"):
        temporally_compatible(sig_aware, MockSignal(), window_days=14)  # type: ignore[arg-type]


def test_compatible_requires_equal_non_null_disease():
    now = datetime.now(UTC)
    disease_a = uuid4()
    disease_b = uuid4()

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

    sig_disease_a = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_a,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now,
        first_seen_at=now,
        locations=(loc,),
    )
    sig_disease_a_2 = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_a,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now - timedelta(days=2),
        first_seen_at=now - timedelta(days=2),
        locations=(loc,),
    )
    sig_disease_b = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_b,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now,
        first_seen_at=now,
        locations=(loc,),
    )
    sig_no_disease_1 = SignalForMatching(
        signal_id=uuid4(),
        disease_id=None,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now,
        first_seen_at=now,
        locations=(loc,),
    )
    sig_no_disease_2 = SignalForMatching(
        signal_id=uuid4(),
        disease_id=None,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now,
        first_seen_at=now,
        locations=(loc,),
    )

    assert compatible(sig_disease_a, sig_disease_a_2, window_days=14, distance_km=50) is True
    assert compatible(sig_disease_a, sig_disease_b, window_days=14, distance_km=50) is False
    assert compatible(sig_no_disease_1, sig_no_disease_2, window_days=14, distance_km=50) is False
    assert compatible(sig_disease_a, sig_no_disease_1, window_days=14, distance_km=50) is False


def test_build_clusters_single_link_transitivity():
    from episignal_backend.events.cluster import build_clusters

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

    # Signal A at Day 0, B at Day 8, C at Day 16.
    # Window = 10 days.
    # A links B (8 <= 10).
    # B links C (8 <= 10).
    # A does not link C directly (16 > 10).
    sig_a = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now,
        first_seen_at=now,
        locations=(loc,),
    )
    sig_b = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now + timedelta(days=8),
        first_seen_at=now + timedelta(days=8),
        locations=(loc,),
    )
    sig_c = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_id,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now + timedelta(days=16),
        first_seen_at=now + timedelta(days=16),
        locations=(loc,),
    )

    clusters, unclusterable = build_clusters(
        [sig_a, sig_b, sig_c],
        window_days=10,
        distance_km=50.0,
    )

    assert len(unclusterable) == 0
    assert len(clusters) == 1
    assert len(clusters[0].signals) == 3
    sig_ids = {s.signal_id for s in clusters[0].signals}
    assert sig_ids == {sig_a.signal_id, sig_b.signal_id, sig_c.signal_id}


def test_build_clusters_different_diseases_and_unclusterable():
    from episignal_backend.events.cluster import build_clusters

    now = datetime.now(UTC)
    disease_a = uuid4()
    disease_b = uuid4()

    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )

    sig_a = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_a,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now,
        first_seen_at=now,
        locations=(loc,),
    )
    sig_b = SignalForMatching(
        signal_id=uuid4(),
        disease_id=disease_b,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now,
        first_seen_at=now,
        locations=(loc,),
    )
    sig_no_disease = SignalForMatching(
        signal_id=uuid4(),
        disease_id=None,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now,
        first_seen_at=now,
        locations=(loc,),
    )

    clusters, unclusterable = build_clusters(
        [sig_a, sig_b, sig_no_disease],
        window_days=14,
        distance_km=50.0,
    )

    assert len(clusters) == 2
    assert {c.disease_id for c in clusters} == {disease_a, disease_b}
    assert len(unclusterable) == 1
    assert unclusterable[0].signal_id == sig_no_disease.signal_id


def test_build_clusters_deterministic_under_shuffling():
    import random

    from episignal_backend.events.cluster import build_clusters

    now = datetime.now(UTC)
    disease_1 = uuid4()
    disease_2 = uuid4()

    loc_cd = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )
    loc_ug = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="UG",
        place_name="Kampala",
        latitude=0.34,
        longitude=32.58,
    )

    signals = [
        SignalForMatching(
            signal_id=uuid4(),
            disease_id=disease_1,
            source_id=uuid4(),
            source_is_official=False,
            credibility_tier=CredibilityTier.MEDIUM,
            published_at=now + timedelta(days=i),
            first_seen_at=now + timedelta(days=i),
            locations=(loc_cd,),
        )
        for i in range(5)
    ] + [
        SignalForMatching(
            signal_id=uuid4(),
            disease_id=disease_2,
            source_id=uuid4(),
            source_is_official=False,
            credibility_tier=CredibilityTier.MEDIUM,
            published_at=now + timedelta(days=i),
            first_seen_at=now + timedelta(days=i),
            locations=(loc_ug,),
        )
        for i in range(3)
    ]

    clusters_1, unclusterable_1 = build_clusters(signals, window_days=14, distance_km=50.0)

    # Shuffled input
    shuffled = list(signals)
    random.Random(42).shuffle(shuffled)
    clusters_2, unclusterable_2 = build_clusters(shuffled, window_days=14, distance_km=50.0)

    assert len(clusters_1) == len(clusters_2)
    for c1, c2 in zip(clusters_1, clusters_2, strict=True):
        assert c1.disease_id == c2.disease_id
        assert [s.signal_id for s in c1.signals] == [s.signal_id for s in c2.signals]
