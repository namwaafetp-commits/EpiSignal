import json
from collections.abc import Callable
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


def client_repeating(
    response_factory: Callable[[httpx.Request], httpx.Response],
) -> GdeltDocClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return response_factory(request)

    transport = httpx.MockTransport(handler)
    return GdeltDocClient(
        client=httpx.Client(transport=transport),
        fallback_client=httpx.Client(transport=transport),
        sleep=lambda _: None,
    )


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

    transport = httpx.MockTransport(handler)
    client = GdeltDocClient(
        client=httpx.Client(transport=transport),
        fallback_client=httpx.Client(transport=transport),
        sleep=lambda _: None,
    )
    with pytest.raises(GdeltUnavailable):
        client.search(RULE, WINDOW)


def test_search_retries_https_timeout_once_over_http() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.scheme == "https":
            raise httpx.ConnectTimeout("timed out", request=request)
        return artlist_response()

    transport = httpx.MockTransport(handler)
    client = GdeltDocClient(
        client=httpx.Client(transport=transport),
        fallback_client=httpx.Client(transport=transport),
        sleep=lambda _: None,
    )

    assert len(client.search(RULE, WINDOW)) == 3
    assert [request.url.scheme for request in requests] == ["https", "http"]
    assert requests[0].url.params == requests[1].url.params
    assert "authorization" not in requests[1].headers


def test_search_uses_http_directly_after_https_timeout() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.scheme == "https":
            raise httpx.ConnectTimeout("timed out", request=request)
        return artlist_response()

    transport = httpx.MockTransport(handler)
    client = GdeltDocClient(
        client=httpx.Client(transport=transport),
        fallback_client=httpx.Client(transport=transport),
        sleep=lambda _: None,
    )

    client.search(RULE, WINDOW)
    client.search(RULE, WINDOW)

    assert [request.url.scheme for request in requests] == ["https", "http", "http"]


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


def test_successful_run_summary_records_attempt_and_success() -> None:
    client = client_returning(httpx.Response(200, json={"articles": []}))

    assert client.search(RULE, WINDOW) == ()
    summary = client.finish_run(1)

    assert (summary.rules_total, summary.rules_attempted, summary.rules_succeeded) == (1, 1, 1)
    assert summary.rules_failed == 0
    assert summary.rules_skipped_circuit == 0
    assert summary.circuit_open is False
    assert all(value == 0 for value in summary.failure_counts.values())


def test_zero_results_reset_the_failure_streak() -> None:
    mode = {"failing": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if mode["failing"]:
            return httpx.Response(503, request=request)
        return httpx.Response(200, json={"articles": []}, request=request)

    transport = httpx.MockTransport(handler)
    client = GdeltDocClient(
        client=httpx.Client(transport=transport),
        fallback_client=httpx.Client(transport=transport),
        sleep=lambda _: None,
    )
    with pytest.raises(GdeltUnavailable):
        client.search(RULE, WINDOW)
    mode["failing"] = False

    assert client.search(RULE, WINDOW) == ()
    summary = client.finish_run(2)
    assert summary.rules_failed == 1
    assert summary.rules_succeeded == 1
    assert summary.circuit_open is False


def test_tls_failure_falls_back_to_http_without_failing_the_rule() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.scheme == "https":
            raise httpx.ConnectError("TLS handshake failed", request=request)
        return httpx.Response(200, json={"articles": []}, request=request)

    transport = httpx.MockTransport(handler)
    client = GdeltDocClient(
        client=httpx.Client(transport=transport),
        fallback_client=httpx.Client(transport=transport),
        sleep=lambda _: None,
    )

    assert client.search(RULE, WINDOW) == ()
    summary = client.finish_run(1)

    assert [request.url.scheme for request in requests] == ["https", "http"]
    assert summary.rules_failed == 0
    assert summary.rules_succeeded == 1
    assert summary.https_attempts == 1
    assert summary.http_attempts == 1
    assert summary.failure_counts["tls_error"] == 0


@pytest.mark.parametrize(
    ("failure_factory", "category"),
    [
        (lambda request: httpx.ConnectTimeout("connect", request=request), "connect_timeout"),
        (lambda request: httpx.ReadTimeout("read", request=request), "read_timeout"),
        (lambda request: httpx.ConnectError("TLS handshake", request=request), "tls_error"),
        (lambda request: httpx.ConnectError("refused", request=request), "other"),
    ],
)
def test_transport_failures_are_classified(
    failure_factory: Callable[[httpx.Request], Exception], category: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise failure_factory(request)

    transport = httpx.MockTransport(handler)
    client = GdeltDocClient(
        client=httpx.Client(transport=transport),
        fallback_client=httpx.Client(transport=transport),
        sleep=lambda _: None,
    )

    with pytest.raises(GdeltUnavailable) as raised:
        client.search(RULE, WINDOW)

    assert raised.value.failure is not None
    assert raised.value.failure.category == category


@pytest.mark.parametrize(
    ("response_factory", "category"),
    [
        (lambda request: httpx.Response(429, request=request), "http_429"),
        (lambda request: httpx.Response(503, request=request), "http_5xx"),
        (
            lambda request: httpx.Response(200, json={"wrong": []}, request=request),
            "invalid_response",
        ),
        (lambda request: httpx.Response(200, text="not JSON", request=request), "parse_error"),
    ],
)
def test_response_failures_are_classified(
    response_factory: Callable[[httpx.Request], httpx.Response], category: str
) -> None:
    client = client_repeating(response_factory)

    with pytest.raises(GdeltUnavailable) as raised:
        client.search(RULE, WINDOW)

    assert raised.value.failure is not None
    assert raised.value.failure.category == category


def test_failed_rule_logs_structured_safe_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = client_returning(httpx.Response(503), httpx.Response(503), httpx.Response(503))

    with caplog.at_level("WARNING"), pytest.raises(GdeltUnavailable):
        client.search(RULE, WINDOW)

    message = caplog.records[-1].message
    assert "rule=Measles" in message
    assert "transport=https" in message
    assert "error=http_5xx" in message
    assert "status_code=503" in message
    assert "elapsed_ms=" in message


def test_circuit_opens_at_eight_failed_rules_and_skips_the_rest() -> None:
    client = client_returning(*[httpx.Response(503) for _ in range(3 * 8)])
    rules = [
        QueryRule(rule_group="known_disease", query=f"disease-{index}", label=f"Rule {index}")
        for index in range(10)
    ]

    for rule in rules:
        if client.circuit_open:
            assert client.search(rule, WINDOW) == ()
        else:
            with pytest.raises(GdeltUnavailable):
                client.search(rule, WINDOW)

    summary = client.finish_run(len(rules))
    assert summary.rules_attempted == 8
    assert summary.rules_failed == 8
    assert summary.rules_skipped_circuit == 2
    assert summary.circuit_open is True


def test_circuit_state_is_fresh_for_the_next_run() -> None:
    mode = {"failing": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if mode["failing"]:
            return httpx.Response(503, request=request)
        return httpx.Response(200, json={"articles": []}, request=request)

    transport = httpx.MockTransport(handler)
    client = GdeltDocClient(
        client=httpx.Client(transport=transport),
        fallback_client=httpx.Client(transport=transport),
        sleep=lambda _: None,
    )
    for index in range(8):
        with pytest.raises(GdeltUnavailable):
            client.search(
                QueryRule(rule_group="known_disease", query=str(index), label=str(index)), WINDOW
            )
    assert client.circuit_open is True

    mode["failing"] = False
    client.begin_run()
    assert client.search(RULE, WINDOW) == ()
    summary = client.finish_run(1)
    assert summary.circuit_open is False
    assert summary.rules_skipped_circuit == 0


def test_run_summary_logs_circuit_open_once(caplog: pytest.LogCaptureFixture) -> None:
    client = client_returning(*[httpx.Response(503) for _ in range(3 * 8)])
    for index in range(8):
        with pytest.raises(GdeltUnavailable):
            client.search(
                QueryRule(rule_group="known_disease", query=str(index), label=str(index)), WINDOW
            )

    with caplog.at_level("WARNING"):
        client.finish_run(9)

    assert sum("gdelt_circuit_open" in record.message for record in caplog.records) == 1
    assert "remaining_rules=1" in caplog.records[-1].message
