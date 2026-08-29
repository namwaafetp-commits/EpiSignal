import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from episignal_backend.ingestion.documents import QueryRule, TimeWindow
from episignal_backend.ingestion.gdelt.api import API_URL, GdeltDocClient, GdeltUnavailable

FIXTURES = Path(__file__).parent / "fixtures"
WINDOW = TimeWindow(
    start=datetime(2026, 8, 26, 7, 30, tzinfo=UTC),
    end=datetime(2026, 8, 26, 7, 50, tzinfo=UTC),
)
RULE = QueryRule(rule_group="known_disease", query="measles", label="Measles")


def client_returning(*responses: httpx.Response) -> GdeltDocClient:
    remaining = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        response = remaining.pop(0)
        response.request = request
        return response

    transport = httpx.MockTransport(handler)
    return GdeltDocClient(client=httpx.Client(transport=transport), sleep=lambda _: None)


def artlist_response() -> httpx.Response:
    return httpx.Response(200, json=json.loads((FIXTURES / "gdelt_artlist.json").read_text()))


def test_search_returns_one_article_per_entry() -> None:
    articles = client_returning(artlist_response()).search(RULE, WINDOW)
    assert len(articles) == 3


def test_search_maps_locale_names_to_codes() -> None:
    articles = client_returning(artlist_response()).search(RULE, WINDOW)
    assert articles[0].language == "es"
    assert articles[0].country_code == "US"


def test_search_parses_the_quantized_seendate() -> None:
    articles = client_returning(artlist_response()).search(RULE, WINDOW)
    assert articles[0].gdelt_seen_at == datetime(2026, 8, 25, 19, 0, tzinfo=UTC)


def test_search_canonicalizes_urls() -> None:
    articles = client_returning(artlist_response()).search(RULE, WINDOW)
    assert articles[0].canonical_url.endswith("2599658")


def test_search_carries_the_rule_identity() -> None:
    articles = client_returning(artlist_response()).search(RULE, WINDOW)
    assert all(article.query_rule_id == RULE.id for article in articles)


def test_search_sends_the_window_as_start_and_end_datetimes() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"articles": []}, request=request)

    client = GdeltDocClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None
    )
    client.search(RULE, WINDOW)

    assert str(captured[0].url).startswith(API_URL)
    assert captured[0].url.params["startdatetime"] == "20260826073000"
    assert captured[0].url.params["enddatetime"] == "20260826075000"
    assert captured[0].url.params["mode"] == "ArtList"
    assert captured[0].url.params["format"] == "json"


def test_an_empty_result_is_not_an_error() -> None:
    client = client_returning(httpx.Response(200, json={"articles": []}))
    assert client.search(RULE, WINDOW) == ()


def test_a_body_that_is_not_json_is_treated_as_empty() -> None:
    # GDELT answers an unmatched query with a bare message rather than JSON.
    client = client_returning(httpx.Response(200, text="No results found."))
    assert client.search(RULE, WINDOW) == ()


def test_search_retries_a_retryable_status_then_succeeds() -> None:
    client = client_returning(httpx.Response(429), artlist_response())
    assert len(client.search(RULE, WINDOW)) == 3


def test_search_raises_when_every_attempt_is_refused() -> None:
    client = client_returning(httpx.Response(503), httpx.Response(503), httpx.Response(503))
    with pytest.raises(GdeltUnavailable):
        client.search(RULE, WINDOW)


def test_search_raises_when_the_transport_refuses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = GdeltDocClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None
    )
    with pytest.raises(GdeltUnavailable):
        client.search(RULE, WINDOW)


def test_search_skips_an_entry_with_no_url() -> None:
    client = client_returning(
        httpx.Response(
            200,
            json={
                "articles": [
                    {"url": "", "title": "x", "seendate": "20260825T190000Z", "domain": "a.test"},
                    {
                        "url": "https://a.test/1",
                        "title": "Measles cases rise",
                        "seendate": "20260825T190000Z",
                        "domain": "a.test",
                        "language": "English",
                        "sourcecountry": "United Kingdom",
                    },
                ]
            },
        )
    )
    articles = client.search(RULE, WINDOW)
    assert len(articles) == 1
    assert articles[0].url == "https://a.test/1"


def test_search_waits_between_requests_when_asked() -> None:
    slept: list[float] = []
    client = client_returning(httpx.Response(429), artlist_response())
    client._sleep = slept.append  # type: ignore[method-assign]
    client.search(RULE, WINDOW)
    assert slept == [1.0]


def test_window_longer_than_a_day_is_accepted() -> None:
    window = TimeWindow(
        start=datetime(2026, 8, 20, tzinfo=UTC), end=datetime(2026, 8, 26, tzinfo=UTC)
    )
    assert len(client_returning(artlist_response()).search(RULE, window)) == 3
    assert window.end - window.start == timedelta(days=6)


ENGLISH_RULE = QueryRule(
    rule_group="known_disease", query="measles", label="Measles", language="en"
)


def test_a_rule_with_a_language_sends_the_sourcelang_operator() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"articles": []}, request=request)

    client = GdeltDocClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None
    )
    client.search(ENGLISH_RULE, WINDOW)

    assert captured[0].url.params["query"] == "measles sourcelang:eng"


def test_an_any_language_rule_sends_no_operator() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"articles": []}, request=request)

    client = GdeltDocClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None
    )
    client.search(RULE, WINDOW)

    assert captured[0].url.params["query"] == "measles"


def test_a_rule_with_a_language_drops_mismatched_entries() -> None:
    # The fixture's three articles are two Spanish and one English.
    articles = client_returning(artlist_response()).search(ENGLISH_RULE, WINDOW)
    assert [article.language for article in articles] == ["en"]


def test_a_rule_with_a_language_keeps_matching_entries() -> None:
    response = httpx.Response(
        200,
        json={
            "articles": [
                {
                    "url": "https://a.test/1",
                    "title": "Measles cases rise",
                    "seendate": "20260825T190000Z",
                    "domain": "a.test",
                    "language": "English",
                    "sourcecountry": "United Kingdom",
                },
                {
                    "url": "https://a.test/2",
                    "title": "Measles cases rise again",
                    "seendate": "20260825T191500Z",
                    "domain": "a.test",
                    "language": "Spanish",
                    "sourcecountry": "Spain",
                },
            ]
        },
    )
    articles = client_returning(response).search(ENGLISH_RULE, WINDOW)
    assert [article.url for article in articles] == ["https://a.test/1"]


def test_an_any_language_rule_keeps_mismatched_entries() -> None:
    articles = client_returning(artlist_response()).search(RULE, WINDOW)
    assert len(articles) == 3
