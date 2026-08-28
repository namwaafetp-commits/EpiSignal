"""Story clustering over geocoded signals.

Pure functions for precision weighting, spatial compatibility, temporal
compatibility, and single-link agglomerative clustering.

This module imports neither SQLAlchemy nor httpx.
"""

import math

from episignal_backend.db.types import Precision
from episignal_backend.events.documents import LocationForMatching

PRECISION_WEIGHTS: dict[Precision, float] = {
    Precision.PLACE: 1.0,
    Precision.ADMIN2: 0.75,
    Precision.ADMIN1: 0.5,
    Precision.COUNTRY: 0.25,
    Precision.UNRESOLVED: 0.0,
}

_PRECISION_RANK: dict[Precision, int] = {
    Precision.PLACE: 4,
    Precision.ADMIN2: 3,
    Precision.ADMIN1: 2,
    Precision.COUNTRY: 1,
    Precision.UNRESOLVED: 0,
}


def precision_weight(precision: Precision) -> float:
    """Return the relative specificity weight of a location precision in 0-1."""
    return PRECISION_WEIGHTS[precision]


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two coordinates in kilometres."""
    r = 6371.0  # Earth radius in kilometres
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def spatially_compatible(
    a: LocationForMatching,
    b: LocationForMatching,
    *,
    distance_km: float = 50.0,
) -> bool:
    """Evaluate spatial compatibility between two locations at their coarsest shared precision.

    - UNRESOLVED always returns False.
    - Differing country codes always return False.
    - COUNTRY precision compares on country_code equality only.
    - ADMIN1 precision compares on admin1 code equality, never distance.
    - ADMIN2 precision compares on admin2 code equality.
    - PLACE precision compares by great-circle distance within distance_km.
    """
    if a.precision == Precision.UNRESOLVED or b.precision == Precision.UNRESOLVED:
        return False

    if not a.country_code or not b.country_code or a.country_code != b.country_code:
        return False

    coarsest = min(a.precision, b.precision, key=lambda p: _PRECISION_RANK[p])

    if coarsest == Precision.COUNTRY:
        return a.country_code == b.country_code

    if coarsest == Precision.ADMIN1:
        return bool(a.admin1 and b.admin1 and a.admin1 == b.admin1)

    if coarsest == Precision.ADMIN2:
        if a.admin1 and b.admin1 and a.admin1 != b.admin1:
            return False
        return bool(a.admin2 and b.admin2 and a.admin2 == b.admin2)

    # Coarsest is PLACE (both are PLACE)
    if a.latitude is None or a.longitude is None or b.latitude is None or b.longitude is None:
        return False

    return haversine_distance_km(a.latitude, a.longitude, b.latitude, b.longitude) <= distance_km
