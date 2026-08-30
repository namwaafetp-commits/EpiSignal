"""The boundaries the geocoding pass depends on.

`GazetteerRepository` answers four questions and nothing else: the country
alias map, the admin1 code for a name inside a country, candidates for a name
in a scope, and the centroid of an admin1 or a country. Keeping it that narrow
is what lets the resolution ladder be tested with tuples.

`GeocodeCacheRepository` and `ExternalGeocoder` are the optional rungs below
the gazetteer: the persistent record of names answered outside it, and the
live service those answers come from. The ladder reaches them only on a
zero-candidate miss, never on an ambiguity.

The repository owns transactions. Nothing above it knows what a session is,
which is why `commit` and `rollback` sit on the Protocol.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from episignal_backend.geocode.documents import (
    Candidate,
    GeocodableSignal,
    MatchForm,
    ResolvedLocation,
)


@runtime_checkable
class GazetteerRepository(Protocol):
    def country_aliases(self) -> Mapping[str, str]: ...

    def admin1_code(self, *, country_code: str, name: str) -> str | None: ...

    def candidates(
        self,
        *,
        name: str,
        form: MatchForm,
        country_code: str | None,
        admin1_code: str | None,
    ) -> Sequence[Candidate]:
        """Rows matching `name` under `form`.

        `country_code` of None searches the whole gazetteer, which is only ever
        done when no country could be resolved.
        """
        ...

    def centroid(self, *, country_code: str, admin1_code: str | None) -> Candidate | None:
        """The admin1 centroid, or the country centroid when `admin1_code` is None."""
        ...


@runtime_checkable
class GeocodeCacheRepository(Protocol):
    """The persistent record of place names answered outside the gazetteer.

    Keyed on the whitespace-collapsed lower-case form of the query plus the
    country scope it was searched under; a `None` scope is the worldwide
    lookup. Implementations apply the same normalization to whatever they are
    handed, so passing the extraction's own string is safe. A lookup that
    misses returns None and never raises.
    """

    def lookup(self, normalized_query: str, country_code: str | None) -> Candidate | None: ...

    def store(
        self, candidate: Candidate, normalized_query: str, country_code: str | None
    ) -> None: ...


@runtime_checkable
class ExternalGeocoder(Protocol):
    """A place lookup answered outside the reviewed gazetteer.

    Consulted only when the gazetteer held no candidate at all, never to break
    a tie between candidates it did hold. A failure is the implementor's to
    absorb: a None is a miss, and no network or parsing error may propagate.
    """

    def lookup(self, name: str, *, country_code: str | None = None) -> Candidate | None: ...


@runtime_checkable
class GeocodeRepository(Protocol):
    def awaiting_geocoding(self, *, limit: int) -> Sequence[GeocodableSignal]: ...

    def stale_geocoding(self, *, limit: int, source: str) -> Sequence[GeocodableSignal]: ...

    def replace_locations(
        self, signal_id: UUID, locations: Sequence[ResolvedLocation], *, source: str
    ) -> None: ...

    def mark_geocoded(self, signal_id: UUID) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class GazetteerMissing(Exception):
    """The gazetteer holds no rows, so nothing can be resolved.

    An operator error, not a signal-level one: it must stop the run rather than
    mark every signal it touches.
    """
