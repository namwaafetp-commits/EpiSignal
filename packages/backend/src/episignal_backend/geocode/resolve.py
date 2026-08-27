"""The resolution ladder.

One rule governs the whole module: ambiguity coarsens and never tie-breaks. No
step chooses among surviving candidates by population, by feature class, or by
any other property. A province centroid is a less precise true statement; the
most populous Springfield is a guess wearing a coordinate.

This module imports neither SQLAlchemy nor httpx.
"""

from episignal_backend.db.types import Precision
from episignal_backend.geocode.documents import MatchForm

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
