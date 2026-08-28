from episignal_backend.db.types import Precision
from episignal_backend.events.cluster import precision_weight


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
    from episignal_backend.db.types import LocationRole
    from episignal_backend.events.cluster import spatially_compatible
    from episignal_backend.events.documents import LocationForMatching

    # Beni and Butembo (~50 km apart)
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
    # 5 km away from Beni
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
    # Kinshasa (~1500 km away)
    kinshasa = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="Kinshasa",
        place_name="Kinshasa",
        latitude=-4.32,
        longitude=15.31,
    )

    # 5 km apart passes with default 50 km distance threshold
    assert spatially_compatible(beni, near_beni, distance_km=50) is True
    # 500+ km apart fails
    assert spatially_compatible(beni, kinshasa, distance_km=50) is False


def test_spatially_compatible_admin1_precision_compares_codes_never_distance():
    from episignal_backend.db.types import LocationRole
    from episignal_backend.events.cluster import spatially_compatible
    from episignal_backend.events.documents import LocationForMatching

    # Place in Province A (North Kivu)
    place_in_kivu = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        latitude=0.50,
        longitude=29.50,
    )
    # Province centroid of North Kivu (same admin1)
    kivu_province = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.ADMIN1,
        country_code="CD",
        admin1="North Kivu",
        latitude=0.50,
        longitude=29.50,
    )
    # Province centroid of Ituri (different admin1, but geographically adjacent/close)
    ituri_province_close = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.ADMIN1,
        country_code="CD",
        admin1="Ituri",
        latitude=0.51,  # ~1 km away
        longitude=29.50,
    )

    # Same admin1 code matches
    assert spatially_compatible(place_in_kivu, kivu_province, distance_km=50) is True
    # Different admin1 code fails even if distance is only ~1 km
    assert spatially_compatible(place_in_kivu, ituri_province_close, distance_km=50) is False


def test_spatially_compatible_country_precision_compares_country_code():
    from episignal_backend.db.types import LocationRole
    from episignal_backend.events.cluster import spatially_compatible
    from episignal_backend.events.documents import LocationForMatching

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
    from episignal_backend.db.types import LocationRole
    from episignal_backend.events.cluster import spatially_compatible
    from episignal_backend.events.documents import LocationForMatching

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
    from episignal_backend.db.types import LocationRole
    from episignal_backend.events.cluster import spatially_compatible
    from episignal_backend.events.documents import LocationForMatching

    # Border towns: Goma (CD) and Gisenyi (RW) are < 5 km apart
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

    # Different country codes must return False regardless of close distance
    assert spatially_compatible(goma, gisenyi, distance_km=50) is False
