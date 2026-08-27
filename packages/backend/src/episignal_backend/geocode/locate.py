"""The geocoding pass.

Orchestration only: it selects signals, runs the ladder over each place, writes
the rows, and advances the signal. It has no failure of its own to report about
a signal, because there is none available to it. An unresolvable place is a
recorded answer, not an error, and the only thing that can stop the run is an
empty gazetteer, which is an operator problem rather than a signal problem.
"""

from dataclasses import dataclass

from episignal_backend.db.types import Precision
from episignal_backend.geocode.protocol import (
    GazetteerMissing,
    GazetteerRepository,
    GeocodeRepository,
)
from episignal_backend.geocode.resolve import resolve_place


@dataclass(frozen=True)
class GeocodingResult:
    examined: int = 0
    located: int = 0
    unresolved: int = 0
    locations: int = 0


def run_geocoding(
    repository: GeocodeRepository,
    gazetteer: GazetteerRepository,
    *,
    limit: int,
    source: str,
    stale: bool = False,
) -> GeocodingResult:
    if not gazetteer.country_aliases():
        repository.rollback()
        raise GazetteerMissing("no country aliases are loaded, so nothing can be scoped")

    signals = (
        repository.stale_geocoding(limit=limit, source=source)
        if stale
        else repository.awaiting_geocoding(limit=limit)
    )

    examined = 0
    located = 0
    unresolved = 0
    written = 0

    for signal in signals:
        resolutions = tuple(resolve_place(place, gazetteer) for place in signal.locations)
        repository.replace_locations(signal.id, resolutions, source=source)
        repository.mark_geocoded(signal.id)
        examined += 1
        written += len(resolutions)
        for resolution in resolutions:
            if resolution.precision is Precision.UNRESOLVED:
                unresolved += 1
            else:
                located += 1

    repository.commit()
    return GeocodingResult(
        examined=examined, located=located, unresolved=unresolved, locations=written
    )
