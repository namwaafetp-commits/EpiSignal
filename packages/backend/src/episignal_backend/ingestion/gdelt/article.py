"""Fetching the publisher's page.

This is the only place EpiSignal reads a third party's website rather than an
API offered to it, so it behaves like a guest: one robots.txt check per domain,
a delay between consecutive requests to the same host, and a User-Agent that
says who is calling and where to complain.

A refusal is expected, not exceptional. `Unfetchable` and `Disallowed` are
distinct because one warrants a retry and the other never will.
"""

import logging
from collections.abc import Callable
from time import monotonic
from time import sleep as default_sleep
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "EpiSignal/0.1 (+https://episignal.org)"
TIMEOUT_SECONDS = 15.0
DELAY_SECONDS = 1.0
MAX_BYTES = 2_000_000
HTML_TYPES = ("text/html", "application/xhtml+xml", "text/plain")

logger = logging.getLogger("episignal_backend.ingestion.gdelt")


class Unfetchable(Exception):
    """The page could not be retrieved. Worth retrying later."""


class Disallowed(Exception):
    """robots.txt forbids this path. Never worth retrying."""


class ArticleFetcher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = default_sleep,
        delay_seconds: float = DELAY_SECONDS,
        user_agent: str = USER_AGENT,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=timeout_seconds, follow_redirects=True, headers={"User-Agent": user_agent}
        )
        self._sleep = sleep
        self._delay_seconds = delay_seconds
        self._user_agent = user_agent
        self._timeout_seconds = timeout_seconds
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_request: dict[str, float] = {}

    def fetch(self, url: str) -> str:
        parsed = urlsplit(url)
        host = parsed.netloc.lower()

        if not self._permitted(parsed.scheme, host, url):
            raise Disallowed(host)

        self._wait_for(host)
        try:
            response = self._client.get(
                url, timeout=self._timeout_seconds, headers={"User-Agent": self._user_agent}
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise Unfetchable(host) from error
        finally:
            self._last_request[host] = monotonic()

        if response.status_code >= 400:
            raise Unfetchable(f"{host} returned {response.status_code}")

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith(HTML_TYPES):
            raise Unfetchable(f"{host} returned {content_type}")

        if len(response.content) > MAX_BYTES:
            raise Unfetchable(f"{host} returned an oversized document")

        return response.text

    def _permitted(self, scheme: str, host: str, url: str) -> bool:
        if host not in self._robots:
            self._robots[host] = self._read_robots(scheme or "https", host)
        rules = self._robots[host]
        # An absent or unreadable robots.txt is permission by convention; a
        # present one that forbids the path is not ours to overrule.
        return True if rules is None else rules.can_fetch(self._user_agent, url)

    def _read_robots(self, scheme: str, host: str) -> RobotFileParser | None:
        location = f"{scheme}://{host}/robots.txt"
        try:
            response = self._client.get(
                location, timeout=self._timeout_seconds, headers={"User-Agent": self._user_agent}
            )
        except (httpx.TimeoutException, httpx.TransportError):
            return None
        if response.status_code >= 400:
            return None
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser

    def _wait_for(self, host: str) -> None:
        previous = self._last_request.get(host)
        if previous is None or self._delay_seconds <= 0:
            return
        remaining = self._delay_seconds - (monotonic() - previous)
        if remaining > 0:
            self._sleep(self._delay_seconds)
