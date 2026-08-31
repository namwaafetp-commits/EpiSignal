"""Story clustering over extracted signals.

Pure functions for precision weighting, spatial compatibility, temporal
compatibility, and single-link agglomerative clustering.

This module imports neither SQLAlchemy nor httpx.
"""

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from episignal_backend.db.types import LocationRole, Precision
from episignal_backend.events.documents import (
    LocationForMatching,
    SignalForMatching,
    StoryCluster,
)

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


def _signal_timestamp(sig: SignalForMatching) -> datetime:
    ts = sig.published_at if sig.published_at is not None else sig.first_seen_at
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise ValueError("Timezone-aware datetime required for temporal comparison")
    return ts


def temporally_compatible(
    a: SignalForMatching,
    b: SignalForMatching,
    *,
    window_days: int = 14,
) -> bool:
    """Evaluate temporal compatibility between two signals within a window in days."""
    ts_a = _signal_timestamp(a)
    ts_b = _signal_timestamp(b)
    diff = abs(ts_a - ts_b)
    return diff <= timedelta(days=window_days)


def representative_location(signal: SignalForMatching) -> LocationForMatching | None:
    """Return the highest-precision primary location in the signal, falling back to any role."""
    if not signal.locations:
        return None
    primary_locs = [loc for loc in signal.locations if loc.location_role == LocationRole.PRIMARY]
    candidates = primary_locs if primary_locs else list(signal.locations)
    return max(candidates, key=lambda loc: _PRECISION_RANK.get(loc.precision, -1))


def compatible(
    a: SignalForMatching,
    b: SignalForMatching,
    *,
    window_days: int = 14,
    distance_km: float = 50.0,
) -> bool:
    """Evaluate whether two signals report the same outbreak.

    Requires:
    1. Equal disease identity: disease_id, or exact normalized disease text.
    2. Temporal compatibility within window_days.
    3. Spatial compatibility between their representative locations within distance_km.
    """
    if a.disease_identity is None or a.disease_identity != b.disease_identity:
        return False

    if not temporally_compatible(a, b, window_days=window_days):
        return False

    loc_a = representative_location(a)
    loc_b = representative_location(b)
    if loc_a is None or loc_b is None:
        return False

    return spatially_compatible(loc_a, loc_b, distance_km=distance_km)


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, i: int) -> int:
        path = []
        while self.parent[i] != i:
            path.append(i)
            i = self.parent[i]
        for node in path:
            self.parent[node] = i
        return i

    def union(self, i: int, j: int) -> None:
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            self.parent[root_i] = root_j


def build_clusters(
    signals: Sequence[SignalForMatching],
    *,
    window_days: int = 14,
    distance_km: float = 50.0,
) -> tuple[tuple[StoryCluster, ...], tuple[SignalForMatching, ...]]:
    """Assemble signals into story clusters using single-link agglomeration.

    Returns:
        A tuple of (clusters, unclusterable_signals).
    """
    clusterable: list[SignalForMatching] = []
    unclusterable: list[SignalForMatching] = []

    for sig in signals:
        rep_loc = representative_location(sig)
        if (
            sig.disease_identity is None
            or rep_loc is None
            or rep_loc.country_code is None
            or rep_loc.precision == Precision.UNRESOLVED
        ):
            unclusterable.append(sig)
        else:
            clusterable.append(sig)

    # Group by disease
    by_disease: dict[str, list[SignalForMatching]] = defaultdict(list)
    for sig in clusterable:
        assert sig.disease_identity is not None
        by_disease[sig.disease_identity].append(sig)

    clusters: list[StoryCluster] = []

    for disease_signals in by_disease.values():
        n = len(disease_signals)
        uf = _UnionFind(n)

        for i in range(n):
            for j in range(i + 1, n):
                if compatible(
                    disease_signals[i],
                    disease_signals[j],
                    window_days=window_days,
                    distance_km=distance_km,
                ):
                    uf.union(i, j)

        groups: dict[int, list[SignalForMatching]] = defaultdict(list)
        for idx, sig in enumerate(disease_signals):
            root = uf.find(idx)
            groups[root].append(sig)

        for group_signals in groups.values():
            sorted_group = sorted(
                group_signals,
                key=lambda s: (_signal_timestamp(s), s.signal_id.bytes),
            )
            clusters.append(StoryCluster(signals=tuple(sorted_group)))

    sorted_clusters = sorted(
        clusters,
        key=lambda c: (
            c.disease_identity or "",
            c.span[0],
            c.signals[0].signal_id.bytes,
        ),
    )
    sorted_unclusterable = sorted(
        unclusterable,
        key=lambda s: (_signal_timestamp(s), s.signal_id.bytes),
    )

    return tuple(sorted_clusters), tuple(sorted_unclusterable)
