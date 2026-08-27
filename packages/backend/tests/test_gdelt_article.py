import httpx
import pytest

from episignal_backend.ingestion.gdelt.article import ArticleFetcher, Disallowed, Unfetchable

ROBOTS_ALLOW = "User-agent: *\nAllow: /\n"
ROBOTS_DENY_ALL = "User-agent: *\nDisallow: /\n"
ROBOTS_DENY_SECTION = "User-agent: *\nDisallow: /private/\n"
PAGE = "<html><body><p>Eighteen students were admitted.</p></body></html>"


def fetcher(routes: dict[str, httpx.Response], delays: list[float] | None = None) -> ArticleFetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        key = str(request.url)
        if key not in routes:
            return httpx.Response(404, request=request)
        response = routes[key]
        response.request = request
        return response

    return ArticleFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=(delays.append if delays is not None else lambda _: None),
        delay_seconds=1.0,
    )


def test_fetches_a_page_when_robots_allows_it() -> None:
    routes = {
        "https://example.vn/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW),
        "https://example.vn/a": httpx.Response(200, text=PAGE),
    }
    assert "Eighteen students" in fetcher(routes).fetch("https://example.vn/a")


def test_refuses_a_path_robots_disallows() -> None:
    routes = {
        "https://example.vn/robots.txt": httpx.Response(200, text=ROBOTS_DENY_ALL),
        "https://example.vn/a": httpx.Response(200, text=PAGE),
    }
    with pytest.raises(Disallowed):
        fetcher(routes).fetch("https://example.vn/a")


def test_allows_a_path_outside_a_disallowed_section() -> None:
    routes = {
        "https://example.vn/robots.txt": httpx.Response(200, text=ROBOTS_DENY_SECTION),
        "https://example.vn/public/a": httpx.Response(200, text=PAGE),
    }
    assert "Eighteen students" in fetcher(routes).fetch("https://example.vn/public/a")


def test_a_missing_robots_file_permits_fetching() -> None:
    routes = {
        "https://example.vn/robots.txt": httpx.Response(404),
        "https://example.vn/a": httpx.Response(200, text=PAGE),
    }
    assert "Eighteen students" in fetcher(routes).fetch("https://example.vn/a")


def test_robots_is_fetched_once_per_domain() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_ALLOW, request=request)
        return httpx.Response(200, text=PAGE, request=request)

    fetch = ArticleFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
        delay_seconds=0.0,
    )
    fetch.fetch("https://example.vn/a")
    fetch.fetch("https://example.vn/b")

    assert requested.count("https://example.vn/robots.txt") == 1


def test_waits_between_two_fetches_of_the_same_domain() -> None:
    delays: list[float] = []
    routes = {
        "https://example.vn/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW),
        "https://example.vn/a": httpx.Response(200, text=PAGE),
        "https://example.vn/b": httpx.Response(200, text=PAGE),
    }
    fetch = fetcher(routes, delays)
    fetch.fetch("https://example.vn/a")
    fetch.fetch("https://example.vn/b")
    assert delays == [1.0]


def test_an_error_status_is_unfetchable() -> None:
    routes = {
        "https://example.vn/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW),
        "https://example.vn/a": httpx.Response(403),
    }
    with pytest.raises(Unfetchable):
        fetcher(routes).fetch("https://example.vn/a")


def test_a_transport_refusal_is_unfetchable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_ALLOW, request=request)
        raise httpx.ConnectTimeout("timed out", request=request)

    fetch = ArticleFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
        delay_seconds=0.0,
    )
    with pytest.raises(Unfetchable):
        fetch.fetch("https://example.vn/a")


def test_a_non_html_response_is_unfetchable() -> None:
    routes = {
        "https://example.vn/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW),
        "https://example.vn/a.pdf": httpx.Response(
            200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}
        ),
    }
    with pytest.raises(Unfetchable):
        fetcher(routes).fetch("https://example.vn/a.pdf")
