from datetime import UTC, datetime, timedelta, timezone

import pytest
from episignal_backend.db.types import ProcessingStatus
from episignal_backend.ingestion.documents import DiscoveredArticle, QueryRule, TimeWindow
from episignal_backend.ingestion.gdelt.article import Disallowed, Unfetchable
from episignal_backend.ingestion.gdelt.connector import GdeltConnector
from episignal_backend.ingestion.protocol import DiscoveryConnector, RetrievalFailed

SEEN = datetime(2026, 8, 26, 7, 45, tzinfo=UTC)
FIRST = datetime(2026, 8, 26, 7, 51, tzinfo=UTC)
NOW = datetime(2026, 8, 26, 7, 52, tzinfo=UTC)

FULL_PAGE = """
<html><head>
<meta property="og:title" content="18 students hospitalised" />
<meta property="og:site_name" content="Example News Vietnam" />
<meta property="article:published_time" content="2026-08-26T07:42:00+07:00" />
</head><body><p>Eighteen students were admitted on Tuesday.</p></body></html>
"""

NO_DATE_PAGE = "<html><body><p>Eleven people fell ill after a shared meal.</p></body></html>"
NO_BODY_PAGE = "<html><head><title>Subscribe</title></head><body><div>Subscribe</div></body></html>"


class FakeSearch:
    def __init__(self, articles: tuple[DiscoveredArticle, ...] = ()) -> None:
        self.articles = articles

    def search(self, rule: QueryRule, window: TimeWindow) -> tuple[DiscoveredArticle, ...]:
        return self.articles


class FakeFetcher:
    def __init__(self, result: str | Exception) -> None:
        self.result = result
        self.calls: list[str] = []

    def fetch(self, url: str) -> str:
        self.calls.append(url)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def article() -> DiscoveredArticle:
    return DiscoveredArticle(
        url="https://example.vn/a",
        canonical_url="https://example.vn/a",
        title="Dos residentes - Example News ( 39 )",
        domain="example.vn",
        gdelt_seen_at=SEEN,
        language="vi",
        country_code="VN",
    )


def connector(page: str | Exception) -> GdeltConnector:
    return GdeltConnector(
        search=FakeSearch(),  # type: ignore[arg-type]
        fetcher=FakeFetcher(page),  # type: ignore[arg-type]
        now=lambda: NOW,
        # The production floor is 200 characters, which every fixture here would
        # trip. The behaviour under test is the decision, not the threshold.
        minimum_body_characters=20,
    )


def test_connector_satisfies_the_protocol() -> None:
    assert isinstance(connector(FULL_PAGE), DiscoveryConnector)


def test_retrieve_prefers_the_publisher_title() -> None:
    signal = connector(FULL_PAGE).retrieve(article(), FIRST)
    assert signal.title == "18 students hospitalised"


def test_retrieve_falls_back_to_the_gdelt_title() -> None:
    signal = connector(NO_DATE_PAGE).retrieve(article(), FIRST)
    assert signal.title == "Dos residentes - Example News ( 39 )"


def test_retrieve_keeps_the_stated_publication_offset() -> None:
    signal = connector(FULL_PAGE).retrieve(article(), FIRST)
    assert signal.published_at == datetime(2026, 8, 26, 7, 42, tzinfo=timezone(timedelta(hours=7)))
    assert signal.published_at_offset_minutes == 420


def test_retrieve_never_substitutes_the_seen_date_for_a_publication_date() -> None:
    signal = connector(NO_DATE_PAGE).retrieve(article(), FIRST)
    assert signal.published_at is None
    assert signal.published_at_offset_minutes is None
    assert signal.gdelt_seen_at == SEEN


def test_retrieve_keeps_the_first_seen_time_it_was_given() -> None:
    signal = connector(FULL_PAGE).retrieve(article(), FIRST)
    assert signal.first_seen_at == FIRST
    assert signal.retrieved_at == NOW


def test_retrieve_names_the_publisher_from_the_page() -> None:
    signal = connector(FULL_PAGE).retrieve(article(), FIRST)
    assert signal.publisher.domain == "example.vn"
    assert signal.publisher.name == "Example News Vietnam"
    assert signal.publisher.country_code == "VN"


def test_retrieve_names_the_publisher_from_the_domain_when_the_page_is_silent() -> None:
    signal = connector(NO_DATE_PAGE).retrieve(article(), FIRST)
    assert signal.publisher.name == "example.vn"


def test_a_page_without_prose_is_a_retrieval_failure() -> None:
    with pytest.raises(RetrievalFailed):
        connector(NO_BODY_PAGE).retrieve(article(), FIRST)


def test_an_unfetchable_page_is_a_retrieval_failure() -> None:
    with pytest.raises(RetrievalFailed):
        connector(Unfetchable("blocked")).retrieve(article(), FIRST)


def test_a_disallowed_page_is_a_retrieval_failure() -> None:
    with pytest.raises(RetrievalFailed):
        connector(Disallowed("example.vn")).retrieve(article(), FIRST)


def test_the_content_hash_changes_when_the_body_changes() -> None:
    first = connector(FULL_PAGE).retrieve(article(), FIRST)
    changed = FULL_PAGE.replace("Eighteen students", "Twenty students")
    second = connector(changed).retrieve(article(), FIRST)
    assert first.content_hash != second.content_hash


def test_stub_for_a_failed_retrieval_is_built_by_the_connector() -> None:
    stub = connector(FULL_PAGE).stub(article(), FIRST)
    assert stub.processing_status is ProcessingStatus.NEEDS_REVIEW
    assert stub.raw_text is None
    assert stub.published_at is None
    assert stub.title == "Dos residentes - Example News ( 39 )"
    assert stub.publisher.name == "example.vn"
    assert len(stub.content_hash) == 64
