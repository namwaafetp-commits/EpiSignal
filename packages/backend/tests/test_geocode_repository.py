from typing import Any
from uuid import uuid4

from episignal_backend.db.types import LocationRole, Precision
from episignal_backend.geocode.documents import Candidate, MatchForm, ResolvedLocation
from episignal_backend.geocode.protocol import (
    GazetteerRepository,
    GeocodeCacheRepository,
    GeocodeRepository,
)
from episignal_backend.geocode.repository import (
    SqlAlchemyGazetteerRepository,
    SqlAlchemyGeocodeCacheRepository,
    SqlAlchemyGeocodeRepository,
)
from sqlalchemy import Delete, Select, Update


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> Any:
        return self._value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = results or []
        self.executed: list[Any] = []
        self.added: list[Any] = []

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return self._results.pop(0) if self._results else FakeResult(None)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class Row:
    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


class SignalRow:
    def __init__(self, signal_id: Any, extraction: Any) -> None:
        self.id = signal_id
        self.ai_extraction = extraction


def place_row(**overrides: Any) -> Row:
    fields: dict[str, Any] = {
        "geonames_id": 2332459,
        "name": "Lagos",
        "precision": "place",
        "country_code": "NG",
        "admin1_code": "05",
        "admin2_code": None,
        "latitude": 6.45,
        "longitude": 3.39,
    }
    fields.update(overrides)
    return Row(**fields)


def test_it_satisfies_the_gazetteer_boundary() -> None:
    assert isinstance(SqlAlchemyGazetteerRepository(FakeSession()), GazetteerRepository)


def test_the_alias_map_comes_from_the_reviewed_seed_file() -> None:
    aliases = SqlAlchemyGazetteerRepository(FakeSession()).country_aliases()
    assert aliases["nigeria"] == "NG"
    assert aliases["niger"] == "NE"


def test_it_turns_rows_into_candidates() -> None:
    session = FakeSession([FakeResult([place_row()])])
    found = SqlAlchemyGazetteerRepository(session).candidates(
        name="Lagos", form=MatchForm.EXACT, country_code="NG", admin1_code=None
    )
    assert len(found) == 1
    assert found[0].geonames_id == 2332459
    assert found[0].latitude == 6.45


def test_a_scoped_query_is_a_select_against_the_gazetteer() -> None:
    session = FakeSession([FakeResult([])])
    SqlAlchemyGazetteerRepository(session).candidates(
        name="Lagos", form=MatchForm.EXACT, country_code="NG", admin1_code="05"
    )
    statement = session.executed[0]
    assert isinstance(statement, Select)
    rendered = str(statement)
    assert "gazetteer_places" in rendered
    assert "normalized_name" in rendered


def test_the_ascii_form_queries_the_ascii_column() -> None:
    session = FakeSession([FakeResult([])])
    SqlAlchemyGazetteerRepository(session).candidates(
        name="Krakow", form=MatchForm.ASCII, country_code="PL", admin1_code=None
    )
    assert "ascii_name" in str(session.executed[0])


def test_the_alternate_form_queries_the_alternate_names_array() -> None:
    session = FakeSession([FakeResult([])])
    SqlAlchemyGazetteerRepository(session).candidates(
        name="Eko", form=MatchForm.ALTERNATE, country_code="NG", admin1_code=None
    )
    assert "alternate_names" in str(session.executed[0])


def test_a_worldwide_query_carries_no_country_filter() -> None:
    session = FakeSession([FakeResult([])])
    SqlAlchemyGazetteerRepository(session).candidates(
        name="Kinshasa", form=MatchForm.EXACT, country_code=None, admin1_code=None
    )
    assert "country_code" not in str(session.executed[0].whereclause)


def test_candidate_queries_are_bounded() -> None:
    # Two rows is all the ladder needs: one means unique, more than one means
    # ambiguous. Fetching every Springfield on earth to count them is waste.
    session = FakeSession([FakeResult([])])
    SqlAlchemyGazetteerRepository(session).candidates(
        name="Springfield", form=MatchForm.EXACT, country_code="US", admin1_code=None
    )
    assert "LIMIT" in str(session.executed[0]).upper()


def test_it_resolves_an_admin1_code_by_either_name_form() -> None:
    session = FakeSession([FakeResult("05")])
    code = SqlAlchemyGazetteerRepository(session).admin1_code(country_code="NG", name="Lagos State")
    assert code == "05"
    rendered = str(session.executed[0])
    assert "normalized_name" in rendered
    assert "ascii_name" in rendered


def test_an_admin1_centroid_is_returned_as_a_candidate() -> None:
    row = place_row(geonames_id=2332453, name="Lagos", precision="admin1")
    session = FakeSession([FakeResult(row)])
    centre = SqlAlchemyGazetteerRepository(session).centroid(country_code="NG", admin1_code="05")
    assert centre is not None
    assert centre.precision == "admin1"


def test_a_missing_centroid_is_none_rather_than_an_error() -> None:
    session = FakeSession([FakeResult(None)])
    assert (
        SqlAlchemyGazetteerRepository(session).centroid(country_code="ZZ", admin1_code=None) is None
    )


def test_it_satisfies_the_geocoding_storage_boundary() -> None:
    assert isinstance(SqlAlchemyGeocodeRepository(FakeSession()), GeocodeRepository)


def test_only_extracted_signals_are_selected() -> None:
    session = FakeSession([FakeResult([])])
    SqlAlchemyGeocodeRepository(session).awaiting_geocoding(limit=10)
    rendered = str(session.executed[0].whereclause)
    assert "processing_status" in rendered
    assert "ai_extraction" in rendered


def test_it_reads_the_places_out_of_the_stored_extraction() -> None:
    extraction = {
        "signal_type": "outbreak_report",
        "summary": "Cholera in Lagos.",
        "locations": [
            {"role": "primary", "country": "Nigeria", "admin1": None, "place_name": "Lagos"}
        ],
    }
    signal_id = uuid4()
    session = FakeSession([FakeResult([SignalRow(signal_id, extraction)])])
    signals = SqlAlchemyGeocodeRepository(session).awaiting_geocoding(limit=10)
    assert len(signals) == 1
    assert signals[0].id == signal_id
    place = signals[0].locations[0]
    assert place.role == LocationRole.PRIMARY
    assert place.country_name == "Nigeria"
    assert place.place_name == "Lagos"


def test_an_extraction_naming_no_places_yields_a_signal_with_no_locations() -> None:
    extraction = {"signal_type": "research", "summary": "A modelling study."}
    session = FakeSession([FakeResult([SignalRow(uuid4(), extraction)])])
    signals = SqlAlchemyGeocodeRepository(session).awaiting_geocoding(limit=10)
    assert signals[0].locations == ()


def test_replacing_locations_deletes_before_it_inserts() -> None:
    session = FakeSession()
    repository = SqlAlchemyGeocodeRepository(session)
    resolved = ResolvedLocation(
        role=LocationRole.PRIMARY,
        country_name="Nigeria",
        place_name="Lagos",
        precision=Precision.PLACE,
        geonames_id=2332459,
        resolved_name="Lagos",
        country_code="NG",
        admin1="05",
        latitude=6.45,
        longitude=3.39,
        confidence=0.95,
    )
    repository.replace_locations(uuid4(), (resolved,), source="geonames-2026-08-27")
    assert isinstance(session.executed[0], Delete)
    assert len(session.added) == 1
    assert session.added[0].geocoding_source == "geonames-2026-08-27"
    assert session.added[0].geocoding_confidence == 0.95


def test_an_unresolved_location_is_stored_with_no_geometry() -> None:
    session = FakeSession()
    repository = SqlAlchemyGeocodeRepository(session)
    resolved = ResolvedLocation(
        role=LocationRole.PRIMARY, place_name="Strelsau", precision=Precision.UNRESOLVED
    )
    repository.replace_locations(uuid4(), (resolved,), source="geonames-2026-08-27")
    stored = session.added[0]
    assert stored.geometry is None
    assert stored.latitude is None
    assert stored.geocoding_confidence is None


def test_marking_geocoded_advances_only_the_processing_status() -> None:
    session = FakeSession()
    SqlAlchemyGeocodeRepository(session).mark_geocoded(uuid4())
    statement = session.executed[0]
    assert isinstance(statement, Update)
    rendered = str(statement)
    assert "processing_status" in rendered
    assert "ai_extraction" not in rendered


def test_stale_selection_asks_for_a_source_other_than_the_current_one() -> None:
    session = FakeSession([FakeResult([])])
    SqlAlchemyGeocodeRepository(session).stale_geocoding(limit=10, source="geonames-2026-08-27")
    rendered = str(session.executed[0])
    assert "geocoding_source" in rendered


def test_the_cache_repository_satisfies_the_cache_boundary() -> None:
    assert isinstance(SqlAlchemyGeocodeCacheRepository(FakeSession()), GeocodeCacheRepository)


def test_a_cache_lookup_queries_the_cache_table_with_the_normalized_query() -> None:
    session = FakeSession([FakeResult(None)])
    found = SqlAlchemyGeocodeCacheRepository(session).lookup("  Bonville  ", "NG")

    assert found is None
    statement = session.executed[0]
    assert isinstance(statement, Select)
    rendered = str(statement)
    assert "geocode_cache" in rendered
    assert "normalized_query" in rendered
    assert "country_code" in rendered
    assert statement.compile().params == {"normalized_query_1": "bonville", "country_code_1": "NG"}


def test_a_worldwide_cache_lookup_matches_the_null_scope() -> None:
    session = FakeSession([FakeResult(None)])
    SqlAlchemyGeocodeCacheRepository(session).lookup("bonville", None)
    where_clause = str(session.executed[0].whereclause)
    assert "IS NULL" in where_clause.upper()


def test_a_cached_row_is_returned_as_a_place_candidate() -> None:
    row = Row(
        resolved_name="Bonville",
        country_code="NG",
        latitude=6.70,
        longitude=3.60,
    )
    session = FakeSession([FakeResult(row)])
    found = SqlAlchemyGeocodeCacheRepository(session).lookup("bonville", "NG")

    assert found is not None
    assert found.geonames_id is None
    assert found.name == "Bonville"
    assert found.precision is Precision.PLACE
    assert found.country_code == "NG"
    assert found.latitude == 6.70


def test_storing_a_hit_deletes_the_old_row_and_writes_the_normalized_answer() -> None:
    session = FakeSession()
    candidate = Candidate(
        geonames_id=None,
        name="Bonville",
        precision=Precision.PLACE,
        country_code="NG",
        admin1_code=None,
        admin2_code=None,
        latitude=6.70,
        longitude=3.60,
    )
    SqlAlchemyGeocodeCacheRepository(session).store(candidate, "Bonville", "NG")

    assert isinstance(session.executed[0], Delete)
    stored = session.added[0]
    assert stored.normalized_query == "bonville"
    assert stored.country_code == "NG"
    assert stored.resolved_name == "Bonville"
    assert stored.latitude == 6.70
    assert stored.longitude == 3.60
