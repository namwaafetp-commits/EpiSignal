from collections.abc import Mapping, Sequence

import pytest
from episignal_backend.db.types import LocationRole, Precision
from episignal_backend.geocode.documents import Candidate, ExtractedPlace, MatchForm
from episignal_backend.geocode.resolve import (
    NOMINATIM_PLACE_CONFIDENCE,
    PLACE_CONFIDENCE_BY_FORM,
    confidence_for,
    resolve_place,
)

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


NOMINATIM_ANSWER = Candidate(
    geonames_id=None,
    name="Bonville",
    precision=Precision.PLACE,
    country_code="NG",
    admin1_code=None,
    admin2_code=None,
    latitude=6.70,
    longitude=3.60,
)


class StubCache:
    """Answers lookups from one scripted row and records everything asked of it."""

    def __init__(self, answer: Candidate | None = None) -> None:
        self._answer = answer
        self.lookups: list[tuple[str, str | None]] = []
        self.stored: list[tuple[Candidate, str, str | None]] = []

    def lookup(self, normalized_query: str, country_code: str | None) -> Candidate | None:
        self.lookups.append((normalized_query, country_code))
        return self._answer

    def store(self, candidate: Candidate, normalized_query: str, country_code: str | None) -> None:
        self.stored.append((candidate, normalized_query, country_code))


class StubNominatim:
    def __init__(self, answer: Candidate | None = None) -> None:
        self._answer = answer
        self.calls: list[tuple[str, str | None]] = []

    def lookup(self, name: str, *, country_code: str | None = None) -> Candidate | None:
        self.calls.append((name, country_code))
        return self._answer


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
    gazetteer = StubGazetteer(by_form={("Lagos", "exact", "NG"): (candidate(2332459, "Lagos"),)})
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
    gazetteer = StubGazetteer(by_form={("Lagos", "exact", "NG"): (candidate(2332459, "Lagos"),)})
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Lagos"),
        gazetteer,
    )
    assert resolved.country_name == "Nigeria"
    assert resolved.place_name == "Lagos"
    assert resolved.role == LocationRole.PRIMARY


def test_a_folded_match_is_used_only_when_the_exact_form_found_nothing() -> None:
    gazetteer = StubGazetteer(by_form={("Krakow", "ascii", "NG"): (candidate(3094802, "Kraków"),)})
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


def test_two_survivors_coarsen_to_the_admin1_centroid() -> None:
    gazetteer = StubGazetteer(
        by_form={
            ("Springfield", "exact", "NG"): (
                candidate(1, "Springfield", latitude=1.0, longitude=1.0),
                candidate(2, "Springfield", latitude=2.0, longitude=2.0),
            )
        },
        admin1="05",
        centroids={
            ("NG", "05"): candidate(
                9001, "Lagos State", precision="admin1", latitude=6.6, longitude=3.5
            )
        },
    )
    resolved = resolve_place(
        ExtractedPlace(
            role=LocationRole.PRIMARY,
            country_name="Nigeria",
            admin1_name="Lagos State",
            place_name="Springfield",
        ),
        gazetteer,
    )
    assert resolved.precision == Precision.ADMIN1
    assert resolved.confidence == 0.55
    assert resolved.latitude == 6.6
    assert resolved.resolved_name == "Lagos State"


def test_coarsening_never_returns_one_of_the_tied_candidates() -> None:
    # The rule the sub-project exists to enforce. Neither candidate may be
    # chosen, by population or by anything else.
    gazetteer = StubGazetteer(
        by_form={
            ("Springfield", "exact", "NG"): (
                candidate(1, "Springfield", latitude=1.0, longitude=1.0),
                candidate(2, "Springfield", latitude=2.0, longitude=2.0),
            )
        },
        admin1="05",
        centroids={
            ("NG", "05"): candidate(
                9001, "Lagos State", precision="admin1", latitude=6.6, longitude=3.5
            )
        },
    )
    resolved = resolve_place(
        ExtractedPlace(
            role=LocationRole.PRIMARY,
            country_name="Nigeria",
            admin1_name="Lagos State",
            place_name="Springfield",
        ),
        gazetteer,
    )
    assert resolved.geonames_id not in {1, 2}


def test_an_ambiguous_name_with_no_admin1_coarsens_to_the_country_centroid() -> None:
    gazetteer = StubGazetteer(
        by_form={
            ("Springfield", "exact", "NG"): (
                candidate(1, "Springfield"),
                candidate(2, "Springfield"),
            )
        },
        centroids={
            ("NG", None): candidate(
                9002, "Nigeria", precision="country", admin1_code=None, latitude=9.0, longitude=8.0
            )
        },
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Springfield"),
        gazetteer,
    )
    assert resolved.precision == Precision.COUNTRY
    assert resolved.confidence == 0.30
    assert resolved.latitude == 9.0


def test_a_name_absent_from_the_gazetteer_coarsens_the_same_way() -> None:
    gazetteer = StubGazetteer(
        centroids={
            ("NG", None): candidate(
                9002, "Nigeria", precision="country", admin1_code=None, latitude=9.0, longitude=8.0
            )
        }
    )
    resolved = resolve_place(
        ExtractedPlace(
            role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Nowheresville"
        ),
        gazetteer,
    )
    assert resolved.precision == Precision.COUNTRY
    assert resolved.place_name == "Nowheresville"


def test_a_country_named_with_no_town_resolves_to_the_country_centroid() -> None:
    gazetteer = StubGazetteer(
        centroids={
            ("NG", None): candidate(
                9002, "Nigeria", precision="country", admin1_code=None, latitude=9.0, longitude=8.0
            )
        }
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.AFFECTED_AREA, country_name="Nigeria"),
        gazetteer,
    )
    assert resolved.precision == Precision.COUNTRY
    assert resolved.role == LocationRole.AFFECTED_AREA


def test_a_country_with_no_centroid_at_all_is_unresolved() -> None:
    gazetteer = StubGazetteer()
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Lagos"),
        gazetteer,
    )
    assert resolved.precision == Precision.UNRESOLVED
    assert resolved.latitude is None
    assert resolved.confidence is None
    assert resolved.country_code == "NG"


def test_a_globally_unique_name_resolves_without_a_country() -> None:
    gazetteer = StubGazetteer(
        by_form={
            ("Kinshasa", "exact", None): (
                candidate(
                    2314302,
                    "Kinshasa",
                    country_code="CD",
                    admin1_code="12",
                    latitude=-4.32,
                    longitude=15.31,
                ),
            )
        }
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, place_name="Kinshasa"), gazetteer
    )
    assert resolved.precision == Precision.PLACE
    assert resolved.country_code == "CD"
    assert resolved.confidence == 0.95


def test_a_globally_ambiguous_name_is_unresolved_rather_than_guessed() -> None:
    gazetteer = StubGazetteer(
        by_form={
            ("Springfield", "exact", None): (
                candidate(1, "Springfield", country_code="US"),
                candidate(2, "Springfield", country_code="AU"),
            )
        }
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, place_name="Springfield"), gazetteer
    )
    assert resolved.precision == Precision.UNRESOLVED
    assert resolved.place_name == "Springfield"
    assert resolved.country_code is None


def test_an_unresolvable_country_name_falls_back_to_the_worldwide_search() -> None:
    gazetteer = StubGazetteer(
        by_form={("Kinshasa", "exact", None): (candidate(2314302, "Kinshasa", country_code="CD"),)}
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Ruritania", place_name="Kinshasa"),
        gazetteer,
    )
    assert resolved.precision == Precision.PLACE
    assert resolved.country_name == "Ruritania"


def test_the_worldwide_search_ignores_the_extracted_admin1() -> None:
    # An admin1 name cannot be scoped without a country, so it is not consulted.
    gazetteer = StubGazetteer(
        by_form={("Kinshasa", "exact", None): (candidate(2314302, "Kinshasa", country_code="CD"),)}
    )
    resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, admin1_name="Somewhere", place_name="Kinshasa"),
        gazetteer,
    )
    assert gazetteer.calls[0] == ("Kinshasa", "exact", None, None)


def test_a_location_naming_nothing_but_a_role_is_unresolved() -> None:
    resolved = resolve_place(ExtractedPlace(role=LocationRole.REPORTING), StubGazetteer())
    assert resolved.precision == Precision.UNRESOLVED
    assert resolved.role == LocationRole.REPORTING


def test_the_external_confidence_sits_below_every_reviewed_form() -> None:
    # Unreviewed data, however good its coordinates look, cannot outrank a row
    # a human chose to seed.
    assert NOMINATIM_PLACE_CONFIDENCE == 0.65
    assert all(score > NOMINATIM_PLACE_CONFIDENCE for score in PLACE_CONFIDENCE_BY_FORM.values())


def test_a_cache_hit_on_a_zero_candidate_miss_resolves_at_place_precision() -> None:
    gazetteer = StubGazetteer(
        centroids={
            ("NG", None): candidate(
                9002, "Nigeria", precision="country", admin1_code=None, latitude=9.0, longitude=8.0
            )
        }
    )
    cache = StubCache(answer=NOMINATIM_ANSWER)
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Bonville"),
        gazetteer,
        cache=cache,
    )
    assert resolved.precision == Precision.PLACE
    assert resolved.resolved_name == "Bonville"
    assert resolved.confidence == NOMINATIM_PLACE_CONFIDENCE
    assert resolved.geonames_id is None


def test_the_cache_is_asked_with_the_collapsed_lower_case_query() -> None:
    cache = StubCache()
    resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Bonville"),
        StubGazetteer(),
        cache=cache,
    )
    assert cache.lookups == [("bonville", "NG")]


def test_a_cache_hit_short_circuits_the_live_lookup() -> None:
    cache = StubCache(answer=NOMINATIM_ANSWER)
    nominatim = StubNominatim(answer=NOMINATIM_ANSWER)
    resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Bonville"),
        StubGazetteer(),
        cache=cache,
        nominatim=nominatim,
    )
    assert nominatim.calls == []
    assert cache.stored == []


def test_a_nominatim_hit_on_a_cache_miss_is_stored_and_then_returned() -> None:
    gazetteer = StubGazetteer(
        centroids={
            ("NG", None): candidate(
                9002, "Nigeria", precision="country", admin1_code=None, latitude=9.0, longitude=8.0
            )
        }
    )
    cache = StubCache()
    nominatim = StubNominatim(answer=NOMINATIM_ANSWER)
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Bonville"),
        gazetteer,
        cache=cache,
        nominatim=nominatim,
    )
    assert resolved.confidence == NOMINATIM_PLACE_CONFIDENCE
    assert cache.stored == [(NOMINATIM_ANSWER, "bonville", "NG")]


def test_an_ambiguous_gazetteer_result_never_reaches_the_cache_or_nominatim() -> None:
    # The invariant: ambiguity coarsens and never tie-breaks. Two known
    # Springfields coarsen; they are never taken to an outside source that
    # would happily pick one.
    gazetteer = StubGazetteer(
        by_form={
            ("Springfield", "exact", "NG"): (
                candidate(1, "Springfield", latitude=1.0, longitude=1.0),
                candidate(2, "Springfield", latitude=2.0, longitude=2.0),
            )
        },
        centroids={
            ("NG", None): candidate(
                9002, "Nigeria", precision="country", admin1_code=None, latitude=9.0, longitude=8.0
            )
        },
    )
    cache = StubCache()
    nominatim = StubNominatim(answer=NOMINATIM_ANSWER)
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Springfield"),
        gazetteer,
        cache=cache,
        nominatim=nominatim,
    )
    assert resolved.precision == Precision.COUNTRY
    assert cache.lookups == []
    assert nominatim.calls == []


def test_a_unique_gazetteer_match_is_preferred_over_the_external_rungs() -> None:
    gazetteer = StubGazetteer(by_form={("Lagos", "exact", "NG"): (candidate(2332459, "Lagos"),)})
    cache = StubCache(answer=NOMINATIM_ANSWER)
    nominatim = StubNominatim(answer=NOMINATIM_ANSWER)
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Lagos"),
        gazetteer,
        cache=cache,
        nominatim=nominatim,
    )
    assert resolved.geonames_id == 2332459
    assert resolved.confidence == 0.95
    assert cache.lookups == []
    assert nominatim.calls == []


def test_a_zero_candidate_miss_with_no_cache_and_no_client_coarsens_as_before() -> None:
    gazetteer = StubGazetteer(
        centroids={
            ("NG", None): candidate(
                9002, "Nigeria", precision="country", admin1_code=None, latitude=9.0, longitude=8.0
            )
        }
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Bonville"),
        gazetteer,
    )
    assert resolved.precision == Precision.COUNTRY
    assert resolved.confidence == 0.30


def test_a_worldwide_miss_consults_the_cache_without_a_country_scope() -> None:
    cache = StubCache(answer=NOMINATIM_ANSWER)
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, place_name="Bonville"),
        StubGazetteer(),
        cache=cache,
    )
    assert cache.lookups == [("bonville", None)]
    assert resolved.precision == Precision.PLACE
    assert resolved.country_code == "NG"


def test_a_worldwide_nominatim_hit_is_stored_under_the_worldwide_key() -> None:
    cache = StubCache()
    nominatim = StubNominatim(answer=NOMINATIM_ANSWER)
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, place_name="Bonville"),
        StubGazetteer(),
        cache=cache,
        nominatim=nominatim,
    )
    assert nominatim.calls == [("Bonville", None)]
    assert cache.stored == [(NOMINATIM_ANSWER, "bonville", None)]
    assert resolved.latitude == pytest.approx(6.70)


def test_an_external_miss_leaves_the_place_to_the_coarsening_ladder() -> None:
    gazetteer = StubGazetteer(
        centroids={
            ("NG", None): candidate(
                9002, "Nigeria", precision="country", admin1_code=None, latitude=9.0, longitude=8.0
            )
        }
    )
    resolved = resolve_place(
        ExtractedPlace(role=LocationRole.PRIMARY, country_name="Nigeria", place_name="Bonville"),
        gazetteer,
        cache=StubCache(),
        nominatim=StubNominatim(),
    )
    assert resolved.precision == Precision.COUNTRY
    assert resolved.place_name == "Bonville"
