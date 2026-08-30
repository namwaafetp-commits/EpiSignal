import httpx
import pytest
from episignal_backend.db.types import Precision
from episignal_backend.geocode.external import REQUEST_DELAY_SECONDS, NominatimClient

USER_AGENT = "EpiSignal/0.1 (episignal test)"
LAGOS_BODY = [
    {
        "place_id": 2332459,
        "osm_type": "node",
        "lat": "6.4530625",
        "lon": "3.3958829",
        "display_name": "Lagos, Lagos Island, Lagos, Nigeria",
        "address": {"city": "Lagos", "country": "Nigeria", "country_code": "ng"},
    }
]


class Harness:
    """A client over a scripted transport, recording requests and sleeps."""

    def __init__(self, *responses: httpx.Response, raises: Exception | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []
        self._responses = list(responses)
        self._raises = raises

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._raises is not None:
            raise self._raises
        response = self._responses.pop(0)
        response.request = request
        return response

    def client(self) -> NominatimClient:
        return NominatimClient(
            user_agent=USER_AGENT,
            transport=httpx.MockTransport(self.handler),
            sleep=self.sleeps.append,
        )


def test_a_lookup_builds_the_search_request_the_policy_expects() -> None:
    harness = Harness(httpx.Response(200, json=LAGOS_BODY))
    harness.client().lookup("Lagos", country_code="NG")

    request = harness.requests[0]
    assert request.url.path == "/search"
    assert request.url.params["q"] == "Lagos"
    assert request.url.params["format"] == "jsonv2"
    assert request.url.params["limit"] == "1"
    assert request.url.params["countrycodes"] == "NG"
    assert request.headers["User-Agent"] == USER_AGENT


def test_a_successful_lookup_returns_a_place_candidate() -> None:
    harness = Harness(httpx.Response(200, json=LAGOS_BODY))
    found = harness.client().lookup("Lagos", country_code="NG")

    assert found is not None
    assert found.geonames_id is None
    assert found.name == "Lagos"
    assert found.precision is Precision.PLACE
    assert found.country_code == "NG"
    assert found.admin1_code is None
    assert found.admin2_code is None
    assert found.latitude == pytest.approx(6.4530625)
    assert found.longitude == pytest.approx(3.3958829)


def test_a_worldwide_lookup_takes_the_country_from_the_response() -> None:
    body = [
        {
            "lat": "-4.325",
            "lon": "15.3222",
            "display_name": "Kinshasa, Democratic Republic of the Congo",
            "address": {"city": "Kinshasa", "country_code": "cd"},
        }
    ]
    harness = Harness(httpx.Response(200, json=body))
    found = harness.client().lookup("Kinshasa")

    assert found is not None
    assert found.country_code == "CD"
    assert "countrycodes" not in harness.requests[0].url.params


def test_an_empty_result_set_is_a_miss() -> None:
    harness = Harness(httpx.Response(200, json=[]))
    assert harness.client().lookup("Nowheresville") is None


def test_a_timeout_is_a_miss_rather_than_an_error() -> None:
    harness = Harness(raises=httpx.ConnectTimeout("timed out"))
    assert harness.client().lookup("Lagos") is None


def test_a_non_200_response_is_a_miss() -> None:
    harness = Harness(httpx.Response(503, text="unavailable"))
    assert harness.client().lookup("Lagos") is None


def test_a_body_that_is_not_json_is_a_miss() -> None:
    harness = Harness(httpx.Response(200, text="<html>gateway error</html>"))
    assert harness.client().lookup("Lagos") is None


def test_an_entry_without_a_display_name_is_a_miss() -> None:
    harness = Harness(httpx.Response(200, json=[{"lat": "6.45", "lon": "3.39"}]))
    assert harness.client().lookup("Lagos") is None


def test_an_entry_without_usable_coordinates_is_a_miss() -> None:
    harness = Harness(httpx.Response(200, json=[{"display_name": "Lagos, Nigeria"}]))
    assert harness.client().lookup("Lagos") is None


def test_coordinates_outside_the_globe_are_a_miss() -> None:
    entry = dict(LAGOS_BODY[0], lat="999.0")
    harness = Harness(httpx.Response(200, json=[entry]))
    assert harness.client().lookup("Lagos") is None


def test_an_entry_with_no_country_at_all_is_a_miss() -> None:
    entry = {"lat": "6.45", "lon": "3.39", "display_name": "Lagos"}
    harness = Harness(httpx.Response(200, json=[entry]))
    assert harness.client().lookup("Lagos") is None


def test_the_first_lookup_waits_for_nothing() -> None:
    harness = Harness(httpx.Response(200, json=LAGOS_BODY))
    harness.client().lookup("Lagos")
    assert harness.sleeps == []


def test_consecutive_lookups_sleep_the_policy_interval_between_them() -> None:
    harness = Harness(httpx.Response(200, json=LAGOS_BODY), httpx.Response(200, json=[]))
    client = harness.client()
    client.lookup("Lagos", country_code="NG")
    client.lookup("Lagos", country_code="NG")
    assert harness.sleeps == [REQUEST_DELAY_SECONDS]
