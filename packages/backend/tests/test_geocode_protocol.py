from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4

from episignal_backend.db.types import LocationRole
from episignal_backend.geocode.documents import (
    Candidate,
    ExtractedPlace,
    GeocodableSignal,
    MatchForm,
    ResolvedLocation,
)
from episignal_backend.geocode.protocol import (
    ExternalGeocoder,
    GazetteerRepository,
    GeocodeCacheRepository,
    GeocodeRepository,
)


class FakeGazetteer:
    def country_aliases(self) -> Mapping[str, str]:
        return {"nigeria": "NG"}

    def admin1_code(self, *, country_code: str, name: str) -> str | None:
        return None

    def candidates(
        self,
        *,
        name: str,
        form: MatchForm,
        country_code: str | None,
        admin1_code: str | None,
    ) -> Sequence[Candidate]:
        return ()

    def centroid(self, *, country_code: str, admin1_code: str | None) -> Candidate | None:
        return None


class FakeGeocodeRepository:
    def awaiting_geocoding(self, *, limit: int) -> Sequence[GeocodableSignal]:
        return ()

    def stale_geocoding(self, *, limit: int, source: str) -> Sequence[GeocodableSignal]:
        return ()

    def replace_locations(
        self, signal_id: UUID, locations: Sequence[ResolvedLocation], *, source: str
    ) -> None:
        return None

    def mark_geocoded(self, signal_id: UUID) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_the_gazetteer_boundary_is_satisfiable_without_a_database() -> None:
    assert isinstance(FakeGazetteer(), GazetteerRepository)


def test_the_storage_boundary_is_satisfiable_without_a_database() -> None:
    assert isinstance(FakeGeocodeRepository(), GeocodeRepository)


def test_the_cache_boundary_is_satisfiable_without_a_database() -> None:
    class FakeCache:
        def lookup(self, normalized_query: str, country_code: str | None) -> Candidate | None:
            return None

        def store(
            self, candidate: Candidate, normalized_query: str, country_code: str | None
        ) -> None:
            return None

    assert isinstance(FakeCache(), GeocodeCacheRepository)


def test_the_external_geocoder_boundary_is_satisfiable_without_a_database() -> None:
    class FakeExternal:
        def lookup(self, name: str, *, country_code: str | None = None) -> Candidate | None:
            return None

    assert isinstance(FakeExternal(), ExternalGeocoder)


def test_a_fake_gazetteer_answers_the_four_questions_the_ladder_asks() -> None:
    gazetteer = FakeGazetteer()
    assert gazetteer.country_aliases()["nigeria"] == "NG"
    assert gazetteer.admin1_code(country_code="NG", name="Lagos") is None
    assert (
        gazetteer.candidates(
            name="Lagos", form=MatchForm.EXACT, country_code="NG", admin1_code=None
        )
        == ()
    )
    assert gazetteer.centroid(country_code="NG", admin1_code=None) is None


def test_a_fake_storage_accepts_a_resolution_without_a_session() -> None:
    repository = FakeGeocodeRepository()
    resolved = ResolvedLocation(role=LocationRole.PRIMARY, precision="unresolved")
    repository.replace_locations(uuid4(), (resolved,), source="geonames-test")
    assert (
        GeocodableSignal(id=uuid4(), locations=(ExtractedPlace(role=LocationRole.PRIMARY),))
        .locations[0]
        .role
        == LocationRole.PRIMARY
    )
