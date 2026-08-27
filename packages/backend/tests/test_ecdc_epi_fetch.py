from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from episignal_backend.ingestion.ecdc_epi import FEED_URL, EcdcEpiConnector

FIXTURES = Path(__file__).parent / "fixtures"
FEED = (FIXTURES / "ecdc_epi_feed.xml").read_text(encoding="utf-8")

# The trimmed feed holds three real items, published 30 March, 20 August and
# 21 August 2026, plus one deliberately old item from January 2025. The window
# starts before all three real items and after the old one.
SINCE = datetime(2026, 3, 1, tzinfo=UTC)
OUT_OF_WINDOW = "https://www.ecdc.europa.eu/en/news-events/epidemiological-update-out-of-window"
NEWS_LINK = (
    "https://www.ecdc.europa.eu/en/news-events/"
    "epidemiological-update-11-august-2026-imported-case-andes-hantavirus-eueea"
)


def connector_for(
    handler: Callable[[httpx.Request], httpx.Response],
    requests: list[httpx.Request],
    sleeps: list[float] | None = None,
) -> EcdcEpiConnector:
    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(record))
    return EcdcEpiConnector(
        client=client,
        sleep=(sleeps.append if sleeps is not None else lambda seconds: None),
    )


def serve(article: httpx.Response | None = None) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == FEED_URL:
            return httpx.Response(200, text=FEED)
        return article or httpx.Response(200, text="<html><body>ok</body></html>")

    return handler


def test_fetch_returns_one_document_per_in_window_item() -> None:
    requests: list[httpx.Request] = []
    documents = connector_for(serve(), requests).fetch(SINCE)
    assert len(documents) == 3


def test_fetch_omits_items_published_before_the_window() -> None:
    requests: list[httpx.Request] = []
    connector_for(serve(), requests).fetch(SINCE)
    assert all(str(request.url) != OUT_OF_WINDOW for request in requests)


def test_fetch_requests_the_feed_once_then_one_article_each() -> None:
    requests: list[httpx.Request] = []
    connector_for(serve(), requests).fetch(SINCE)
    assert sum(1 for request in requests if str(request.url) == FEED_URL) == 1
    assert len(requests) == 4


def test_fetch_stores_the_article_html_in_the_payload() -> None:
    requests: list[httpx.Request] = []
    documents = connector_for(serve(), requests).fetch(SINCE)
    assert documents[0].payload["article_html"] == "<html><body>ok</body></html>"
    assert documents[0].payload["feed"]["link"] == NEWS_LINK


def test_fetch_shares_one_retrieved_at_across_the_run() -> None:
    requests: list[httpx.Request] = []
    documents = connector_for(serve(), requests).fetch(SINCE)
    assert len({document.retrieved_at for document in documents}) == 1
    assert documents[0].retrieved_at.tzinfo is not None


def test_inclusive_keeps_an_item_published_exactly_at_the_boundary() -> None:
    boundary = datetime(2026, 8, 20, 11, 39, 42, tzinfo=UTC)
    requests: list[httpx.Request] = []
    inclusive = connector_for(serve(), requests).fetch(boundary, inclusive=True)
    exclusive = connector_for(serve(), []).fetch(boundary)
    assert len(inclusive) == len(exclusive) + 1


def test_a_failing_article_becomes_a_recorded_error_not_an_exception() -> None:
    # The run must continue: one unreachable article is a per-document failure
    # the pipeline counts, not a reason to abandon the other items.
    requests: list[httpx.Request] = []
    documents = connector_for(serve(httpx.Response(500)), requests, sleeps=[]).fetch(SINCE)
    assert len(documents) == 3
    assert all("article_error" in document.payload for document in documents)
    assert all("article_html" not in document.payload for document in documents)


def test_a_recorded_article_error_carries_only_the_exception_class() -> None:
    requests: list[httpx.Request] = []
    documents = connector_for(serve(httpx.Response(500)), requests, sleeps=[]).fetch(SINCE)
    assert documents[0].payload["article_error"] == "HTTPStatusError"


def test_an_article_is_retried_three_times_before_being_recorded_as_failed() -> None:
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    connector_for(serve(httpx.Response(503)), requests, sleeps=sleeps).fetch(SINCE)
    article_requests = [request for request in requests if str(request.url) != FEED_URL]
    assert len(article_requests) == 9
    assert sleeps == [1.0, 2.0] * 3


def test_a_failing_feed_ends_the_run() -> None:
    # A source that changed shape must not report a clean, empty success.
    requests: list[httpx.Request] = []
    connector = connector_for(lambda request: httpx.Response(500), requests, sleeps=[])
    with pytest.raises(httpx.HTTPStatusError):
        connector.fetch(SINCE)


def test_a_feed_without_a_channel_is_rejected() -> None:
    requests: list[httpx.Request] = []
    connector = connector_for(lambda request: httpx.Response(200, text="<rss/>"), requests)
    with pytest.raises(ValueError):
        connector.fetch(SINCE)
