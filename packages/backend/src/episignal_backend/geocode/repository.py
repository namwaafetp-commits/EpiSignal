"""The storage boundary for geocoding.

The only module in `geocode/` that imports SQLAlchemy, and the only one that
owns transactions. Deliberately unable to decide anything: it fetches candidates
and writes rows, and the ladder above it chooses.
"""

from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any
from uuid import UUID

from geoalchemy2.elements import WKTElement
from sqlalchemy import ColumnElement, Select, delete, or_, select, update
from sqlalchemy.orm import Session

from episignal_backend.db.types import LocationRole, Precision, ProcessingStatus
from episignal_backend.geocode.documents import (
    Candidate,
    ExtractedPlace,
    GeocodableSignal,
    MatchForm,
    ResolvedLocation,
)
from episignal_backend.geocode.normalize import ascii_form, cache_key, normalized_form
from episignal_backend.models import GazetteerPlace, GeocodeCache, Signal, SignalLocation
from episignal_backend.seeds import load_country_aliases

# Two is enough to answer the only question the ladder asks: is this name
# unique here? One row means yes, two means no, and the rest are irrelevant.
CANDIDATE_LIMIT = 2


@lru_cache(maxsize=1)
def _aliases() -> Mapping[str, str]:
    return {alias.name: alias.country_code for alias in load_country_aliases()}


def _candidate(row: GazetteerPlace) -> Candidate:
    return Candidate(
        geonames_id=row.geonames_id,
        name=row.name,
        precision=row.precision,
        country_code=row.country_code,
        admin1_code=row.admin1_code,
        admin2_code=row.admin2_code,
        latitude=row.latitude,
        longitude=row.longitude,
    )


class SqlAlchemyGazetteerRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def country_aliases(self) -> Mapping[str, str]:
        return _aliases()

    def _scoped(
        self,
        statement: Select[tuple[GazetteerPlace]],
        country_code: str | None,
        admin1_code: str | None,
    ) -> Select[tuple[GazetteerPlace]]:
        if country_code is not None:
            statement = statement.where(GazetteerPlace.country_code == country_code)
            if admin1_code is not None:
                statement = statement.where(GazetteerPlace.admin1_code == admin1_code)
        return statement

    def candidates(
        self,
        *,
        name: str,
        form: MatchForm,
        country_code: str | None,
        admin1_code: str | None,
    ) -> Sequence[Candidate]:
        if form is MatchForm.EXACT:
            predicate = GazetteerPlace.normalized_name == normalized_form(name)
        elif form is MatchForm.ASCII:
            predicate = GazetteerPlace.ascii_name == ascii_form(name)
        else:
            predicate = GazetteerPlace.alternate_names.any(
                normalized_form(name)  # type: ignore[arg-type]
            )
        statement = self._scoped(
            select(GazetteerPlace).where(predicate), country_code, admin1_code
        ).limit(CANDIDATE_LIMIT)
        return tuple(_candidate(row) for row in self._session.execute(statement).scalars())

    def admin1_code(self, *, country_code: str, name: str) -> str | None:
        return self._session.execute(
            select(GazetteerPlace.admin1_code)
            .where(
                GazetteerPlace.country_code == country_code,
                GazetteerPlace.precision == Precision.ADMIN1,
                or_(
                    GazetteerPlace.normalized_name == normalized_form(name),
                    GazetteerPlace.ascii_name == ascii_form(name),
                ),
            )
            .limit(1)
        ).scalar_one_or_none()

    def centroid(self, *, country_code: str, admin1_code: str | None) -> Candidate | None:
        precision = Precision.COUNTRY if admin1_code is None else Precision.ADMIN1
        statement = select(GazetteerPlace).where(
            GazetteerPlace.country_code == country_code,
            GazetteerPlace.precision == precision,
        )
        if admin1_code is not None:
            statement = statement.where(GazetteerPlace.admin1_code == admin1_code)
        row = self._session.execute(statement.limit(1)).scalar_one_or_none()
        return None if row is None else _candidate(row)


def _scope_predicate(country_code: str | None) -> ColumnElement[bool]:
    """Match the stored scope exactly, including the NULL that is the worldwide key."""
    if country_code is None:
        return GeocodeCache.country_code.is_(None)
    return GeocodeCache.country_code == country_code


class SqlAlchemyGeocodeCacheRepository:
    """The storage side of the external-place cache.

    Rows are unreviewed answers, so the repository decides nothing: it keys on
    the cache-key form of the query and hands back whatever was stored, rebuilt
    as a place-precision candidate. `store` deletes before it inserts, in the
    same spirit as `replace_locations` — a re-lookup overwrites, and a cache
    row has no history worth reconciling. The rows ride the run's transaction,
    so a rolled-back pass leaves no half-written cache behind.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def lookup(self, normalized_query: str, country_code: str | None) -> Candidate | None:
        row = self._session.execute(
            select(GeocodeCache).where(
                GeocodeCache.normalized_query == cache_key(normalized_query),
                _scope_predicate(country_code),
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        # The columns the cache does not carry (the geonames id, the admin
        # codes) were never stored, so the rebuilt candidate cannot invent them.
        return Candidate(
            geonames_id=None,
            name=row.resolved_name,
            precision=Precision.PLACE,
            country_code=row.country_code,
            admin1_code=None,
            admin2_code=None,
            latitude=row.latitude,
            longitude=row.longitude,
        )

    def store(self, candidate: Candidate, normalized_query: str, country_code: str | None) -> None:
        query = cache_key(normalized_query)
        self._session.execute(
            delete(GeocodeCache).where(
                GeocodeCache.normalized_query == query,
                _scope_predicate(country_code),
            )
        )
        self._session.add(
            GeocodeCache(
                normalized_query=query,
                country_code=country_code,
                resolved_name=candidate.name,
                latitude=candidate.latitude,
                longitude=candidate.longitude,
            )
        )


def _places(extraction: Any) -> tuple[ExtractedPlace, ...]:
    """Read the locations out of a stored extraction.

    Tolerant of a missing `locations` key and of nulls inside it, because the
    schema makes every field but the role optional and an older row may predate
    a field entirely. Not tolerant of an unknown role: that is a corrupted row
    rather than a sparse one.
    """
    if not isinstance(extraction, dict):
        return ()
    raw = extraction.get("locations") or ()
    return tuple(
        ExtractedPlace(
            role=LocationRole(item["role"]),
            country_name=item.get("country"),
            admin1_name=item.get("admin1"),
            place_name=item.get("place_name"),
        )
        for item in raw
    )


def _point(resolved: ResolvedLocation) -> WKTElement | None:
    if resolved.latitude is None or resolved.longitude is None:
        return None
    return WKTElement(f"POINT({resolved.longitude} {resolved.latitude})", srid=4326)


class SqlAlchemyGeocodeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _signals(self, statement: Select[tuple[Signal]]) -> Sequence[GeocodableSignal]:
        rows = self._session.execute(statement).scalars()
        return tuple(
            GeocodableSignal(id=row.id, locations=_places(row.ai_extraction)) for row in rows
        )

    def awaiting_geocoding(self, *, limit: int) -> Sequence[GeocodableSignal]:
        # The enforcement of the pipeline order: `classified`, `normalized`, and
        # `duplicate` are simply not selectable here.
        return self._signals(
            select(Signal)
            .where(
                Signal.processing_status == ProcessingStatus.EXTRACTED,
                Signal.ai_extraction.is_not(None),
            )
            .order_by(Signal.first_seen_at)
            .limit(limit)
        )

    def stale_geocoding(self, *, limit: int, source: str) -> Sequence[GeocodableSignal]:
        superseded = (
            select(SignalLocation.signal_id)
            .where(SignalLocation.geocoding_source.is_distinct_from(source))
            .distinct()
        )
        return self._signals(
            select(Signal)
            .where(
                Signal.processing_status == ProcessingStatus.GEOCODED,
                Signal.ai_extraction.is_not(None),
                Signal.id.in_(superseded),
            )
            .order_by(Signal.first_seen_at)
            .limit(limit)
        )

    def replace_locations(
        self, signal_id: UUID, locations: Sequence[ResolvedLocation], *, source: str
    ) -> None:
        # Delete then insert rather than upsert. The extraction is the sole
        # input, so the current answer is the whole answer and there is no
        # partial state worth reconciling.
        self._session.execute(delete(SignalLocation).where(SignalLocation.signal_id == signal_id))
        for resolved in locations:
            self._session.add(
                SignalLocation(
                    signal_id=signal_id,
                    location_role=resolved.role,
                    country_name=resolved.country_name,
                    admin1_name=resolved.admin1_name,
                    place_name=resolved.place_name,
                    precision=resolved.precision,
                    geonames_id=resolved.geonames_id,
                    resolved_name=resolved.resolved_name,
                    country_code=resolved.country_code,
                    admin1=resolved.admin1,
                    admin2=resolved.admin2,
                    latitude=resolved.latitude,
                    longitude=resolved.longitude,
                    geometry=_point(resolved),
                    geocoding_source=source,
                    geocoding_confidence=resolved.confidence,
                )
            )

    def mark_geocoded(self, signal_id: UUID) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(processing_status=ProcessingStatus.GEOCODED)
        )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
