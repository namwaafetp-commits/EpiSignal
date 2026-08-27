from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4

import pytest
from episignal_backend.db.types import LocationRole, Precision
from episignal_backend.geocode.documents import (
    Candidate,
    ExtractedPlace,
    GeocodableSignal,
    MatchForm,
    ResolvedLocation,
)
from episignal_backend.geocode.locate import GeocodingResult, run_geocoding
from episignal_backend.geocode.protocol import GazetteerMissing

SOURCE = "geonames-2026-08-27"

LAGOS = Candidate(
    geonames_id=2332459,
    name="Lagos",
    precision=Precision.PLACE,
    country_code="NG",
    admin1_code="05",
    admin2_code=None,
    latitude=6.45,
    longitude=3.39,
)


class Gazetteer:
    def __init__(self, *, empty: bool = False) -> None:
        self.empty = empty

    def country_aliases(self) -> Mapping[str, str]:
        return {} if self.empty else {"nigeria": "NG"}

    def admin1_code(self, *, country_code: str, name: str) -> str | None:
        return None

    def candidates(
        self, *, name: str, form: MatchForm, country_code: str | None, admin1_code: str | None
    ) -> Sequence[Candidate]:
        if self.empty or form is not MatchForm.EXACT or name != "Lagos":
            return ()
        return (LAGOS,)

    def centroid(self, *, country_code: str, admin1_code: str | None) -> Candidate | None:
        return None


class Storage:
    def __init__(self, signals: Sequence[GeocodableSignal] = (), stale: Sequence[GeocodableSignal] = ()) -> None:
        self._signals = signals
        self._stale = stale
        self.written: dict[UUID, tuple[ResolvedLocation, ...]] = {}
        self.geocoded: list[UUID] = []
        self.commits = 0
        self.rollbacks = 0

    def awaiting_geocoding(self, *, limit: int) -> Sequence[GeocodableSignal]:
        return self._signals[:limit]

    def stale_geocoding(self, *, limit: int, source: str) -> Sequence[GeocodableSignal]:
        return self._stale[:limit]

    def replace_locations(
        self, signal_id: UUID, locations: Sequence[ResolvedLocation], *, source: str
    ) -> None:
        self.written[signal_id] = tuple(locations)

    def mark_geocoded(self, signal_id: UUID) -> None:
        self.geocoded.append(signal_id)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def signal_named(place_name: str | None, country: str | None = "Nigeria") -> GeocodableSignal:
    return GeocodableSignal(
        id=uuid4(),
        locations=(
            ExtractedPlace(
                role=LocationRole.PRIMARY, country_name=country, place_name=place_name
            ),
        ),
    )


def test_it_resolves_and_advances_a_signal() -> None:
    signal = signal_named("Lagos")
    storage = Storage(signals=(signal,))
    result = run_geocoding(storage, Gazetteer(), limit=10, source=SOURCE)
    assert result == GeocodingResult(examined=1, located=1, unresolved=0, locations=1)
    assert storage.geocoded == [signal.id]
    assert storage.written[signal.id][0].precision == Precision.PLACE


def test_a_signal_whose_places_all_fail_still_advances() -> None:
    # Absence of a coordinate is not a processing failure. Sending it to review
    # would fill the queue with places no gazetteer of this size will hold.
    signal = signal_named("Nowheresville")
    storage = Storage(signals=(signal,))
    result = run_geocoding(storage, Gazetteer(), limit=10, source=SOURCE)
    assert storage.geocoded == [signal.id]
    assert result.unresolved == 1
    assert result.located == 0
    assert storage.written[signal.id][0].precision == Precision.UNRESOLVED


def test_a_signal_naming_no_places_advances_with_no_rows() -> None:
    signal = GeocodableSignal(id=uuid4())
    storage = Storage(signals=(signal,))
    result = run_geocoding(storage, Gazetteer(), limit=10, source=SOURCE)
    assert storage.geocoded == [signal.id]
    assert storage.written[signal.id] == ()
    assert result == GeocodingResult(examined=1, located=0, unresolved=0, locations=0)


def test_the_pass_commits_once_when_it_finishes() -> None:
    storage = Storage(signals=(signal_named("Lagos"), signal_named("Lagos")))
    run_geocoding(storage, Gazetteer(), limit=10, source=SOURCE)
    assert storage.commits == 1
    assert storage.rollbacks == 0


def test_an_empty_gazetteer_stops_the_run_instead_of_marking_signals() -> None:
    storage = Storage(signals=(signal_named("Lagos"),))
    with pytest.raises(GazetteerMissing):
        run_geocoding(storage, Gazetteer(empty=True), limit=10, source=SOURCE)
    assert storage.geocoded == []
    assert storage.rollbacks == 1


def test_the_limit_bounds_what_the_pass_examines() -> None:
    storage = Storage(signals=tuple(signal_named("Lagos") for _ in range(5)))
    result = run_geocoding(storage, Gazetteer(), limit=2, source=SOURCE)
    assert result.examined == 2


def test_the_stale_pass_reads_from_the_stale_selection() -> None:
    fresh = signal_named("Lagos")
    stale = signal_named("Lagos")
    storage = Storage(signals=(fresh,), stale=(stale,))
    run_geocoding(storage, Gazetteer(), limit=10, source=SOURCE, stale=True)
    assert storage.geocoded == [stale.id]


def test_nothing_in_the_pass_can_send_a_signal_to_review() -> None:
    storage = Storage(signals=(signal_named("Nowheresville"),))
    run_geocoding(storage, Gazetteer(), limit=10, source=SOURCE)
    assert not hasattr(storage, "mark_needs_review")
