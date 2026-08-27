from uuid import uuid4

import pytest
from episignal_backend.db.types import LocationRole, Precision
from episignal_backend.geocode.documents import (
    Candidate,
    ExtractedPlace,
    GeocodableSignal,
    MatchForm,
    ResolvedLocation,
)
from pydantic import ValidationError


def test_precision_is_ordered_from_specific_to_absent() -> None:
    assert [member.value for member in Precision] == [
        "place",
        "admin2",
        "admin1",
        "country",
        "unresolved",
    ]


def test_precision_stores_its_values_not_its_member_names() -> None:
    assert Precision.ADMIN1 == "admin1"
    assert str(Precision.UNRESOLVED) == "unresolved"


def test_an_extracted_place_keeps_the_extraction_strings_verbatim() -> None:
    place = ExtractedPlace(
        role=LocationRole.PRIMARY,
        country_name="DR Congo",
        admin1_name="Équateur",
        place_name="Bikoro",
    )
    assert place.country_name == "DR Congo"
    assert place.admin1_name == "Équateur"


def test_an_extracted_place_may_name_nothing_at_all() -> None:
    place = ExtractedPlace(role=LocationRole.REPORTING)
    assert place.country_name is None
    assert place.admin1_name is None
    assert place.place_name is None


def test_a_candidate_carries_the_precision_of_its_own_row() -> None:
    candidate = Candidate(
        geonames_id=2314302,
        name="Bikoro",
        precision="place",
        country_code="CD",
        admin1_code="01",
        admin2_code=None,
        latitude=-0.75,
        longitude=18.13,
    )
    assert candidate.precision == "place"
    assert candidate.country_code == "CD"


def test_a_candidate_rejects_a_country_code_that_is_not_two_letters() -> None:
    with pytest.raises(ValidationError):
        Candidate(
            geonames_id=1,
            name="Nowhere",
            precision="place",
            country_code="CDX",
            admin1_code=None,
            admin2_code=None,
            latitude=0.0,
            longitude=0.0,
        )


def test_an_unresolved_location_carries_no_coordinate_and_no_confidence() -> None:
    resolved = ResolvedLocation(
        role=LocationRole.PRIMARY,
        country_name="Ruritania",
        admin1_name=None,
        place_name="Strelsau",
        precision="unresolved",
    )
    assert resolved.latitude is None
    assert resolved.longitude is None
    assert resolved.confidence is None
    assert resolved.geonames_id is None


def test_a_geocodable_signal_carries_the_places_its_extraction_named() -> None:
    signal_id = uuid4()
    signal = GeocodableSignal(
        id=signal_id,
        locations=(ExtractedPlace(role=LocationRole.PRIMARY, place_name="Lagos"),),
    )
    assert signal.id == signal_id
    assert len(signal.locations) == 1


def test_a_geocodable_signal_may_name_no_places() -> None:
    assert GeocodableSignal(id=uuid4()).locations == ()


def test_the_match_forms_are_tried_in_this_order() -> None:
    assert [member.value for member in MatchForm] == ["exact", "ascii", "alternate"]
