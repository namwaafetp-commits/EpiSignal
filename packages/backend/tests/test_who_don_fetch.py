from datetime import UTC, datetime

import httpx
import pytest
from episignal_backend.ingestion.who_don import PAGE_SIZE, WhoDonConnector

SINCE = datetime(2026, 5, 28, tzinfo=UTC)


def item(index: int) -> dict[str, object]:
    return {
        "UrlName": f"2026-DON{index}",
        "DonId": f"2026-DON{index}",
        "Title": f"Outbreak {index}",
        "PublicationDateAndTime": "2026-08-14T15:38:29Z",
        "Overview": "<p>Body</p>",
    }


def connector_for(handler: object, requests: list[httpx.Request]) -> WhoDonConnector:
    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)  # type: ignore[operator]

    client = httpx.Client(transport=httpx.MockTransport(record))
    return WhoDonConnector(client=client, sleep=lambda seconds: None)


def test_fetch_returns_one_raw_document_per_item() -> None:
    requests: list[httpx.Request] = []
    connector = connector_for(
        lambda request: httpx.Response(200, json={"value": [item(1), item(2)]}), requests
    )
    documents = connector.fetch(SINCE)
    assert len(documents) == 2
    assert documents[0].payload["DonId"] == "2026-DON1"
    assert documents[0].retrieved_at.tzinfo is not None


def test_fetch_filters_and_orders_by_publication_time() -> None:
    requests: list[httpx.Request] = []
    connector = connector_for(lambda request: httpx.Response(200, json={"value": []}), requests)
    connector.fetch(SINCE)
    query = requests[0].url.params
    assert query["$filter"] == "PublicationDateAndTime gt 2026-05-28T00:00:00Z"
    assert query["$orderby"] == "PublicationDateAndTime asc"
    assert query["$top"] == str(PAGE_SIZE)


def test_fetch_pages_until_a_short_page_arrives() -> None:
    requests: list[httpx.Request] = []
    pages = [
        {"value": [item(index) for index in range(PAGE_SIZE)]},
        {"value": [item(999)]},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[len(requests) - 1])

    connector = connector_for(handler, requests)
    documents = connector.fetch(SINCE)
    assert len(documents) == PAGE_SIZE + 1
    assert requests[1].url.params["$skip"] == str(PAGE_SIZE)


def test_fetch_retries_a_server_error_then_succeeds() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if len(requests) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"value": [item(1)]})

    connector = connector_for(handler, requests)
    assert len(connector.fetch(SINCE)) == 1
    assert len(requests) == 3


def test_fetch_raises_after_exhausting_retries() -> None:
    requests: list[httpx.Request] = []
    connector = connector_for(lambda request: httpx.Response(503), requests)
    with pytest.raises(httpx.HTTPError):
        connector.fetch(SINCE)
    assert len(requests) == 3


def test_fetch_does_not_retry_a_client_error() -> None:
    requests: list[httpx.Request] = []
    connector = connector_for(lambda request: httpx.Response(404), requests)
    with pytest.raises(httpx.HTTPError):
        connector.fetch(SINCE)
    assert len(requests) == 1
