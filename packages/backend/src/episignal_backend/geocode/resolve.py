"""The resolution ladder.

One rule governs the whole module: ambiguity coarsens and never tie-breaks. No
step chooses among surviving candidates by population, by feature class, or by
any other property. A province centroid is a less precise true statement; the
most populous Springfield is a guess wearing a coordinate.

When the gazetteer holds no candidate at all for a name — a miss, not an
ambiguity — the ladder may consult the geocode cache and then Nominatim. Those
answers are place-precision data nobody on this project has reviewed, so they
score below every reviewed form, and an ambiguous name never reaches them: an
outside source widens the world, and widening is what the coarsening path is
for, never a way of choosing between known candidates.
"""

import enum

from episignal_backend.db.types import Precision
from episignal_backend.geocode.documents import (
    Candidate,
    ExtractedPlace,
    MatchForm,
    ResolvedLocation,
)
from episignal_backend.geocode.normalize import cache_key, resolve_country
from episignal_backend.geocode.protocol import (
    ExternalGeocoder,
    GazetteerRepository,
    GeocodeCacheRepository,
)

PLACE_CONFIDENCE_BY_FORM = {
    MatchForm.EXACT: 0.95,
    MatchForm.ASCII: 0.85,
    MatchForm.ALTERNATE: 0.75,
}
COARSE_CONFIDENCE_BY_PRECISION = {
    Precision.ADMIN2: 0.70,
    Precision.ADMIN1: 0.55,
    Precision.COUNTRY: 0.30,
}
# Below every reviewed form, including an alternate-name match: a cache or
# Nominatim answer is place-precision data nobody on this project has reviewed.
NOMINATIM_PLACE_CONFIDENCE = 0.65

FORMS = (MatchForm.EXACT, MatchForm.ASCII, MatchForm.ALTERNATE)


class MatchFailure(enum.Enum):
    """Why a name did not yield exactly one gazetteer candidate.

    The two failures are kept apart because they mean opposite things. A miss
    may be taken to the cache and Nominatim; an ambiguity goes straight to
    coarsening and never to an external lookup.
    """

    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


def confidence_for(precision: Precision, form: MatchForm | None) -> float | None:
    """How much to trust a resolution, given only how it was reached.

    Derived, never invented and never taken from a model. A reviewer reading a
    row can therefore reconstruct why it holds the number it holds.
    """
    if precision is Precision.UNRESOLVED:
        return None
    if precision is Precision.PLACE:
        if form is None:
            raise ValueError("a place-precision match must record the form that matched it")
        return PLACE_CONFIDENCE_BY_FORM[form]
    return COARSE_CONFIDENCE_BY_PRECISION[precision]


def _accept(
    place: ExtractedPlace,
    found: Candidate,
    *,
    form: MatchForm | None,
    precision: Precision | None = None,
) -> ResolvedLocation:
    reached = found.precision if precision is None else precision
    return ResolvedLocation(
        role=place.role,
        country_name=place.country_name,
        admin1_name=place.admin1_name,
        place_name=place.place_name,
        precision=reached,
        geonames_id=found.geonames_id,
        resolved_name=found.name,
        country_code=found.country_code,
        admin1=found.admin1_code,
        admin2=found.admin2_code,
        latitude=found.latitude,
        longitude=found.longitude,
        confidence=confidence_for(reached, form),
    )


def _unique_match(
    gazetteer: GazetteerRepository,
    name: str,
    *,
    country_code: str | None,
    admin1_code: str | None,
) -> tuple[Candidate, MatchForm] | MatchFailure:
    """The one candidate for `name`, or why there is not exactly one.

    A form that returns several candidates stops the search rather than falling
    through to a looser form. Looser forms can only widen the set, so trying
    them after an ambiguous result would be a slower way of reaching the same
    ambiguity. A miss is reported as such, because a miss — unlike an
    ambiguity — may be taken to the external lookups.
    """
    for form in FORMS:
        found = gazetteer.candidates(
            name=name, form=form, country_code=country_code, admin1_code=admin1_code
        )
        if len(found) == 1:
            return found[0], form
        if found:
            return MatchFailure.AMBIGUOUS
    return MatchFailure.MISSING


def _unresolved(place: ExtractedPlace, *, country_code: str | None = None) -> ResolvedLocation:
    return ResolvedLocation(
        role=place.role,
        country_name=place.country_name,
        admin1_name=place.admin1_name,
        place_name=place.place_name,
        precision=Precision.UNRESOLVED,
        country_code=country_code,
        confidence=None,
    )


def _coarsen(
    place: ExtractedPlace,
    gazetteer: GazetteerRepository,
    *,
    country_code: str,
    admin1_code: str | None,
) -> ResolvedLocation:
    """Answer at the least specific precision that is still true."""
    if admin1_code is not None:
        centre = gazetteer.centroid(country_code=country_code, admin1_code=admin1_code)
        if centre is not None:
            return _accept(place, centre, form=None, precision=Precision.ADMIN1)
    centre = gazetteer.centroid(country_code=country_code, admin1_code=None)
    if centre is not None:
        return _accept(place, centre, form=None, precision=Precision.COUNTRY)
    return _unresolved(place, country_code=country_code)


def _accept_external(place: ExtractedPlace, found: Candidate) -> ResolvedLocation:
    """A PLACE-precision answer from outside the reviewed gazetteer.

    Scored with `NOMINATIM_PLACE_CONFIDENCE` rather than `confidence_for`,
    because that function derives a reviewed form and the external rungs have
    none: the answer's provenance is the source column stamped beside it.
    """
    return ResolvedLocation(
        role=place.role,
        country_name=place.country_name,
        admin1_name=place.admin1_name,
        place_name=place.place_name,
        precision=Precision.PLACE,
        geonames_id=found.geonames_id,
        resolved_name=found.name,
        country_code=found.country_code,
        admin1=found.admin1_code,
        admin2=found.admin2_code,
        latitude=found.latitude,
        longitude=found.longitude,
        confidence=NOMINATIM_PLACE_CONFIDENCE,
    )


def _external_match(
    place: ExtractedPlace,
    *,
    cache: GeocodeCacheRepository | None,
    nominatim: ExternalGeocoder | None,
    name: str,
    country_code: str | None,
) -> ResolvedLocation | None:
    """The cache, then Nominatim, for a name the gazetteer has never heard of.

    Reached only on a zero-candidate miss. A cache hit is returned as it was
    stored; a Nominatim hit is stored before it is returned, so the answer is
    paid for once. `country_code` is the scope the name was searched under,
    None for the worldwide lookup.
    """
    if cache is not None:
        cached = cache.lookup(cache_key(name), country_code)
        if cached is not None:
            return _accept_external(place, cached)
    if nominatim is not None:
        found = nominatim.lookup(name, country_code=country_code)
        if found is not None:
            if cache is not None:
                cache.store(found, cache_key(name), country_code)
            return _accept_external(place, found)
    return None


def _worldwide(
    place: ExtractedPlace,
    gazetteer: GazetteerRepository,
    *,
    cache: GeocodeCacheRepository | None,
    nominatim: ExternalGeocoder | None,
) -> ResolvedLocation:
    """The only search run without a country scope.

    Reached when no country was extracted, or none resolved. A name unique in
    the whole gazetteer is safe to accept; anything else is left unresolved,
    because there is no scope left to coarsen into — though a true miss may
    still be answered by the external rungs, since no country can be wrong
    there either.
    """
    if place.place_name:
        match = _unique_match(gazetteer, place.place_name, country_code=None, admin1_code=None)
        if isinstance(match, tuple):
            found, form = match
            return _accept(place, found, form=form)
        if match is MatchFailure.MISSING:
            external = _external_match(
                place,
                cache=cache,
                nominatim=nominatim,
                name=place.place_name,
                country_code=None,
            )
            if external is not None:
                return external
    return _unresolved(place)


def resolve_place(
    place: ExtractedPlace,
    gazetteer: GazetteerRepository,
    *,
    cache: GeocodeCacheRepository | None = None,
    nominatim: ExternalGeocoder | None = None,
) -> ResolvedLocation:
    """Run the ladder over one extracted place, exactly once.

    `cache` and `nominatim` are the optional external rungs, consulted only on
    a zero-candidate miss; with neither passed, the ladder answers exactly as
    it always has.
    """
    country_code = resolve_country(place.country_name, gazetteer.country_aliases())
    if country_code is None:
        return _worldwide(place, gazetteer, cache=cache, nominatim=nominatim)

    admin1_code = None
    if place.admin1_name:
        admin1_code = gazetteer.admin1_code(country_code=country_code, name=place.admin1_name)

    if place.place_name:
        match = _unique_match(
            gazetteer, place.place_name, country_code=country_code, admin1_code=admin1_code
        )
        if isinstance(match, tuple):
            found, form = match
            return _accept(place, found, form=form)
        if match is MatchFailure.MISSING:
            external = _external_match(
                place,
                cache=cache,
                nominatim=nominatim,
                name=place.place_name,
                country_code=country_code,
            )
            if external is not None:
                return external

    return _coarsen(place, gazetteer, country_code=country_code, admin1_code=admin1_code)
