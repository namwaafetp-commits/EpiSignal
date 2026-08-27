"""The resolution ladder.

One rule governs the whole module: ambiguity coarsens and never tie-breaks. No
step chooses among surviving candidates by population, by feature class, or by
any other property. A province centroid is a less precise true statement; the
most populous Springfield is a guess wearing a coordinate.
"""

from episignal_backend.db.types import Precision
from episignal_backend.geocode.documents import (
    Candidate,
    ExtractedPlace,
    MatchForm,
    ResolvedLocation,
)
from episignal_backend.geocode.normalize import resolve_country
from episignal_backend.geocode.protocol import GazetteerRepository

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

FORMS = (MatchForm.EXACT, MatchForm.ASCII, MatchForm.ALTERNATE)


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
) -> tuple[Candidate, MatchForm] | None:
    """The one candidate for `name`, or None when there is not exactly one.

    A form that returns several candidates stops the search rather than falling
    through to a looser form. Looser forms can only widen the set, so trying
    them after an ambiguous result would be a slower way of reaching the same
    ambiguity.
    """
    for form in FORMS:
        found = gazetteer.candidates(
            name=name, form=form, country_code=country_code, admin1_code=admin1_code
        )
        if len(found) == 1:
            return found[0], form
        if found:
            return None
    return None


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


def _worldwide(place: ExtractedPlace, gazetteer: GazetteerRepository) -> ResolvedLocation:
    """The only search run without a country scope.

    Reached when no country was extracted, or none resolved. A name unique in
    the whole gazetteer is safe to accept; anything else is left unresolved,
    because there is no scope left to coarsen into.
    """
    if place.place_name:
        match = _unique_match(gazetteer, place.place_name, country_code=None, admin1_code=None)
        if match is not None:
            found, form = match
            return _accept(place, found, form=form)
    return _unresolved(place)


def resolve_place(place: ExtractedPlace, gazetteer: GazetteerRepository) -> ResolvedLocation:
    """Run the ladder over one extracted place, exactly once."""
    country_code = resolve_country(place.country_name, gazetteer.country_aliases())
    if country_code is None:
        return _worldwide(place, gazetteer)

    admin1_code = None
    if place.admin1_name:
        admin1_code = gazetteer.admin1_code(country_code=country_code, name=place.admin1_name)

    if place.place_name:
        match = _unique_match(
            gazetteer, place.place_name, country_code=country_code, admin1_code=admin1_code
        )
        if match is not None:
            found, form = match
            return _accept(place, found, form=form)

    return _coarsen(place, gazetteer, country_code=country_code, admin1_code=admin1_code)
