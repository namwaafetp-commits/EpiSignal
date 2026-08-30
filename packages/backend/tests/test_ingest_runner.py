from datetime import UTC, datetime

import pytest
from episignal_backend.ingest_runner import parse_arguments


def test_the_connector_name_is_required() -> None:
    with pytest.raises(SystemExit):
        parse_arguments([])


def test_an_unknown_connector_is_rejected() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["ecdc"])


def test_since_defaults_to_none() -> None:
    assert parse_arguments(["who-don"]).since is None


def test_since_is_parsed_as_an_inclusive_utc_date() -> None:
    parsed = parse_arguments(["who-don", "--since", "2026-01-01"])
    assert parsed.since == datetime(2026, 1, 1, tzinfo=UTC)


def test_a_malformed_since_is_rejected() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["who-don", "--since", "last-tuesday"])
