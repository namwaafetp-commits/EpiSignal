from collections.abc import Mapping, Sequence

import pytest
from episignal_backend.db.types import LocationRole, Precision
from episignal_backend.geocode.documents import Candidate, ExtractedPlace, MatchForm
from episignal_backend.geocode.resolve import confidence_for, resolve_place

ALIASES: Mapping[str, str] = {"nigeria": "NG", "democratic republic of the congo": "CD"}


def candidate(
    geonames_id: int,
    name: str,
    *,
    precision: str = "place",
    country_code: str = "NG",
    admin1_code: str | None = "05",
    admin2_code: str | None = None,
    latitude: float = 6.45,
    longitude: float = 3.39,
) -> Candidate:
    return Candidate(
        geonames_id=geonames_id,
        name=name,
        precision=precision,
        country_code=country_code,
        admin1_code=admin1_code,
        admin2_code=admin2_code,
        latitude=latitude,
        longitude=longitude,
    )


class StubGazetteer:
    """Answers from a script, so the ladder's choices are the only variable."""

    def __init__(
        self,
        *,
        by_form: dict[tuple[str, str, str | None], Sequence[Candidate]] | None = None,
        admin1: str | None = None,
        centroids: dict[tuple[str, str | None], Candidate] | None = None,
        aliases: Mapping[str, str] | None = None,
    ) -> None:
        self._by_form = by_form or {}
        self._admin1 = admin1
        self._centroids = centroids or {}
        self._aliases = aliases if aliases is not None else ALIASES
        self.calls: list[tuple[str, str, str | None, str | None]] = []

    def country_aliases(self) -> Mapping[str, str]:
        return self._aliases

    def admin1_code(self, *, country_code: str, name: str) -> str | None:
        return self._admin1

    def candidates(
        self, *, name: str, form: MatchForm, country_code: str | None, admin1_code: str | None
    ) -> Sequence[Candidate]:
        self.calls.append((name, form.value, country_code, admin1_code))
        return self._by_form.get((name, form.value, country_code), ())

    def centroid(self, *, country_code: str, admin1_code: str | None) -> Candidate | None:
        return self._centroids.get((country_code, admin1_code))


def test_an_exact_place_match_is_the_most_confident_answer() -> None:
    assert confidence_for(Precision.PLACE, MatchForm.EXACT) == 0.95


def test_a_folded_place_match_scores_below_an_exact_one() -> None:
    assert confidence_for(Precision.PLACE, MatchForm.ASCII) == 0.85


def test_an_alternate_name_match_scores_below_a_folded_one() -> None:
    assert confidence_for(Precision.PLACE, MatchForm.ALTERNATE) == 0.75


def test_coarser_precision_scores_lower_regardless_of_form() -> None:
    assert confidence_for(Precision.ADMIN2, MatchForm.EXACT) == 0.70
    assert confidence_for(Precision.ADMIN1, None) == 0.55
    assert confidence_for(Precision.COUNTRY, None) == 0.30


def test_an_unresolved_location_has_no_confidence_rather_than_zero() -> None:
    assert confidence_for(Precision.UNRESOLVED, None) is None


def test_a_place_precision_without_a_form_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        confidence_for(Precision.PLACE, None)


def test_a_single_exact_match_inside_a_country_is_accepted_at_place_precision() -> None:
    gazetteer = StubGazetteer(
        by_form={("Lagos", "exact", "NG"): (candidate(2332459, "Lagos"),)}
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Lagos"),
        gazetteer,
    )
    assert resolved.precision == Precision.PLACE
    assert resolved.geonames_id == 2332459
    assert resolved.resolved_name == "Lagos"
    assert resolved.confidence == 0.95
    assert resolved.latitude == 6.45


def test_the_extraction_strings_survive_resolution_unmodified() -> None:
    gazetteer = StubGazetteer(
        by_form={("Lagos", "exact", "NG"): (candidate(2332459, "Lagos"),)}
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Lagos"),
        gazetteer,
    )
    assert resolved.country_name == "Nigeria"
    assert resolved.place_name == "Lagos"
    assert resolved.role == LocationRole.PRIMARY


def test_a_folded_match_is_used_only_when_the_exact_form_found_nothing() -> None:
    gazetteer = StubGazetteer(
        by_form={("Krakow", "ascii", "NG"): (candidate(3094802, "Kraków"),)}
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Krakow"),
        gazetteer,
    )
    assert resolved.confidence == 0.85
    assert [call[1] for call in gazetteer.calls] == ["exact", "ascii"]


def test_an_admin2_row_is_accepted_at_admin2_precision() -> None:
    gazetteer = StubGazetteer(
        by_form={
            ("Ituri", "exact", "CD"): (
                candidate(
                    212228,
                    "Ituri",
                    precision="admin2",
                    country_code="CD",
                    admin1_code="10",
                    admin2_code="1002",
                ),
            )
        }
    )
    resolved = resolve_place(
        ExtractedPlace(
            role=LocationRole.PRIMARY,
            country_name="Democratic Republic of the Congo",
            place_name="Ituri",
        ),
        gazetteer,
    )
    assert resolved.precision == Precision.ADMIN2
    assert resolved.confidence == 0.70
    assert resolved.admin2 == "1002"


def test_a_resolved_admin1_narrows_the_scope_before_the_name_is_matched() -> None:
    gazetteer = StubGazetteer(
        by_form={("Lagos", "exact", "NG"): (candidate(2332459, "Lagos"),)}, admin1="05"
    )
    resolve_place(
        ExtractedPlace(
            role=LocationRole.PRIMARY,
            country_name="Nigeria",
            admin1_name="Lagos State",
            place_name="Lagos",
        ),
        gazetteer,
    )
    assert gazetteer.calls[0] == ("Lagos", "exact", "NG", "05")
