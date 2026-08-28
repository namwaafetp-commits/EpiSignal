"""Story clustering over geocoded signals.

Pure functions for precision weighting, spatial compatibility, temporal
compatibility, and single-link agglomerative clustering.

This module imports neither SQLAlchemy nor httpx.
"""

from episignal_backend.db.types import Precision

PRECISION_WEIGHTS: dict[Precision, float] = {
    Precision.PLACE: 1.0,
    Precision.ADMIN2: 0.75,
    Precision.ADMIN1: 0.5,
    Precision.COUNTRY: 0.25,
    Precision.UNRESOLVED: 0.0,
}


def precision_weight(precision: Precision) -> float:
    """Return the relative specificity weight of a location precision in 0-1."""
    return PRECISION_WEIGHTS[precision]
