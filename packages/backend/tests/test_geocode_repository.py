from typing import Any

from episignal_backend.geocode.documents import MatchForm
from episignal_backend.geocode.protocol import GazetteerRepository
from episignal_backend.geocode.repository import SqlAlchemyGazetteerRepository
from sqlalchemy import Select


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

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return self._results.pop(0) if self._results else FakeResult(None)


class Row:
    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


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
    code = SqlAlchemyGazetteerRepository(session).admin1_code(
        country_code="NG", name="Lagos State"
    )
    assert code == "05"
    rendered = str(session.executed[0])
    assert "normalized_name" in rendered
    assert "ascii_name" in rendered


def test_an_admin1_centroid_is_returned_as_a_candidate() -> None:
    row = place_row(geonames_id=2332453, name="Lagos", precision="admin1")
    session = FakeSession([FakeResult(row)])
    centre = SqlAlchemyGazetteerRepository(session).centroid(
        country_code="NG", admin1_code="05"
    )
    assert centre is not None
    assert centre.precision == "admin1"


def test_a_missing_centroid_is_none_rather_than_an_error() -> None:
    session = FakeSession([FakeResult(None)])
    assert (
        SqlAlchemyGazetteerRepository(session).centroid(country_code="ZZ", admin1_code=None)
        is None
    )
