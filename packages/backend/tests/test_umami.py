from datetime import UTC, datetime

import httpx
import pytest
from episignal_backend.briefing.umami import UmamiApiError, UmamiClient

START = datetime(2026, 9, 15, 12, tzinfo=UTC)
END = datetime(2026, 9, 17, 12, tzinfo=UTC)


def test_umami_client_reads_paginated_event_data_pivot_with_bearer_auth() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            json={
                "data": (
                    [
                        {
                            "sessionId": "session-a",
                            "eventName": "event_impression",
                            "propertyKeys": ["event_id", "surface", "position_bucket"],
                            "propertyValues": ["EVT-00000001", "briefing", "1-5"],
                        }
                    ]
                    if page == 1
                    else [
                        {
                            "sessionId": "session-b",
                            "eventName": "event_impression",
                            "propertyKeys": ["event_id", "surface", "position_bucket"],
                            "propertyValues": ["EVT-00000002", "briefing", "6-10"],
                        }
                    ]
                ),
                "count": 2,
                "page": page,
                "pageSize": 1,
            },
        )

    with UmamiClient(
        base_url="https://analytics.example",
        website_id="website-id",
        api_token="server-token",
        transport=httpx.MockTransport(handler),
        page_size=1,
    ) as client:
        records = client.fetch_event_records("event_impression", START, END)

    assert [record.session_id for record in records] == ["session-a", "session-b"]
    assert records[0].properties == {
        "event_id": "EVT-00000001",
        "surface": "briefing",
        "position_bucket": "1-5",
    }
    assert len(requests) == 2
    assert requests[0].url.path == "/api/websites/website-id/event-data-pivot"
    assert requests[0].url.params["eventName"] == "event_impression"
    assert requests[0].url.params["startAt"] == str(int(START.timestamp() * 1000))
    assert requests[0].headers["authorization"] == "Bearer server-token"


def test_umami_client_rejects_malformed_response_without_returning_payload() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"data": {"sessionId": "secret"}})
    )

    with (
        UmamiClient(
            base_url="https://analytics.example",
            website_id="website-id",
            api_token="server-token",
            transport=transport,
        ) as client,
        pytest.raises(UmamiApiError, match="response shape"),
    ):
        client.fetch_event_records("event_impression", START, END)


def test_umami_client_surfaces_http_and_timeout_failures_as_safe_errors() -> None:
    http_failure = httpx.MockTransport(
        lambda request: httpx.Response(503, text="private response body")
    )
    with (
        UmamiClient(
            base_url="https://analytics.example",
            website_id="website-id",
            api_token="server-token",
            transport=http_failure,
        ) as client,
        pytest.raises(UmamiApiError, match="HTTP 503") as error,
    ):
        client.fetch_event_records("event_impression", START, END)
    assert "private response body" not in str(error.value)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret timeout details", request=request)

    with (
        UmamiClient(
            base_url="https://analytics.example",
            website_id="website-id",
            api_token="server-token",
            transport=httpx.MockTransport(timeout),
        ) as client,
        pytest.raises(UmamiApiError, match="timed out"),
    ):
        client.fetch_event_records("event_impression", START, END)
