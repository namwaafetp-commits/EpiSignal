from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from episignal_backend.ingestion.gdelt.extract import extract_page, parse_timestamp

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_reads_the_open_graph_publication_time_and_offset() -> None:
    page = extract_page(fixture("article_og_time.html"))
    assert page.published_at == datetime(2026, 8, 26, 7, 42, tzinfo=timezone(timedelta(hours=7)))
    assert page.published_at_offset_minutes == 420


def test_prefers_the_open_graph_title_over_the_document_title() -> None:
    page = extract_page(fixture("article_og_time.html"))
    assert page.title == "18 students hospitalised after unexplained illness"
    assert page.site_name == "Example News Vietnam"


def test_excludes_navigation_and_footer_from_the_body() -> None:
    page = extract_page(fixture("article_og_time.html"))
    assert "Eighteen students were admitted" in page.body
    assert "Home" not in page.body
    assert "Copyright" not in page.body


def test_reads_json_ld_date_published() -> None:
    page = extract_page(fixture("article_jsonld.html"))
    assert page.published_at == datetime(2026, 8, 25, 18, 30, tzinfo=UTC)
    assert page.published_at_offset_minutes == 0
    assert page.title == "Cholera cases rise in the delta"


def test_reads_a_time_element_datetime() -> None:
    page = extract_page(fixture("article_time_tag.html"))
    assert page.published_at == datetime(2026, 8, 24, 9, 15, tzinfo=timezone(timedelta(hours=2)))
    assert page.published_at_offset_minutes == 120


def test_a_page_without_a_date_still_yields_a_body() -> None:
    page = extract_page(fixture("article_no_date.html"))
    assert page.published_at is None
    assert page.published_at_offset_minutes is None
    assert "eleven cases" in page.body


def test_a_page_without_prose_yields_an_empty_body() -> None:
    page = extract_page(fixture("article_no_body.html"))
    assert page.body == ""


@pytest.mark.parametrize(
    ("value", "expected_offset"),
    [
        ("2026-08-26T07:42:00+07:00", 420),
        ("2026-08-25T18:30:00Z", 0),
        ("2026-08-25T18:30:00+00:00", 0),
        ("2026-08-24T09:15:00-05:00", -300),
    ],
)
def test_parse_timestamp_preserves_the_stated_offset(value: str, expected_offset: int) -> None:
    parsed = parse_timestamp(value)
    assert parsed is not None
    assert parsed[1] == expected_offset


def test_parse_timestamp_returns_no_offset_for_a_bare_date() -> None:
    parsed = parse_timestamp("2026-08-24")
    assert parsed is not None
    # A date with no time zone states a day, not an instant. Inventing an offset
    # would fabricate precision the publisher did not give.
    assert parsed[1] is None


@pytest.mark.parametrize("value", ["", "   ", "not a date", "26/08/2026"])
def test_parse_timestamp_rejects_unparseable_values(value: str) -> None:
    assert parse_timestamp(value) is None
