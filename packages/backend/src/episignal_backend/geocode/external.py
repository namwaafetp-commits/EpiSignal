"""The Nominatim place-search client: the one network adapter in this package.

`external.py` is deliberately the only module here that imports an HTTP client,
and the seams test is what keeps that a deliberate act. Everything above this
file answers from reviewed seed data or from the geocode cache; the resolution
ladder consults Nominatim only when the gazetteer held no candidate at all,
never to break a tie between candidates it did hold.

Nominatim is unreviewed crowd data, so every answer is recorded with its source
stamped on it and cached for reuse, and every failure — timeout, error status,
empty result, malformed body — is logged and returned as None. A miss leaves
the place to the coarsening ladder; it never interrupts a run.

The published usage policy asks at most one request per second from a client,
so the sleep between consecutive live lookups is built in — and injected, so
tests never wait.
"""

import logging
from collections.abc import Callable
from time import sleep as default_sleep
from typing import Any

import httpx
from pydantic import ValidationError

from episignal_backend.db.types import Precision
from episignal_backend.geocode.documents import Candidate

logger = logging.getLogger("episignal_backend.geocode.external")

DEFAULT_BASE_URL = "https://nominatim.openstreetmap.org"
DEFAULT_USER_AGENT = "EpiSignal/0.1 (episignal backend)"
DEFAULT_TIMEOUT_SECONDS = 10.0
SEARCH_PATH = "/search"
# The usage policy bound: one request per second, per client, and a run is a
# client. A run that names several unknown places honours this between calls.
REQUEST_DELAY_SECONDS = 1.0


class NominatimClient:
    """A `/search` lookup that answers with a Candidate or None, never an error."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent},
            transport=transport,
        )
        self._queried = False

    def lookup(self, name: str, *, country_code: str | None = None) -> Candidate | None:
        parameters: dict[str, str] = {
            "q": name,
            "format": "jsonv2",
            "limit": "1",
            # jsonv2 alone names no country; `addressdetails` is what lets a
            # worldwide lookup say which country it resolved to.
            "addressdetails": "1",
        }
        if country_code is not None:
            parameters["countrycodes"] = country_code
        if self._queried:
            self._sleep(REQUEST_DELAY_SECONDS)
        self._queried = True

        try:
            response = self._client.get(f"{self._base_url}{SEARCH_PATH}", params=parameters)
        except httpx.HTTPError as error:
            logger.warning("Nominatim lookup for %r failed (%s)", name, type(error).__name__)
            return None
        if response.status_code != 200:
            logger.warning("Nominatim returned HTTP %d for %r", response.status_code, name)
            return None
        try:
            entries = response.json()
        except ValueError:
            logger.warning("Nominatim returned a body that is not JSON for %r", name)
            return None
        if not isinstance(entries, list) or not entries:
            logger.info("Nominatim found no place for %r", name)
            return None
        return self._candidate(entries[0], scope=country_code)

    def _candidate(self, entry: Any, *, scope: str | None) -> Candidate | None:
        """Turn the first result entry into a Candidate, or None if it cannot be."""
        if not isinstance(entry, dict):
            logger.warning("Nominatim returned a malformed entry")
            return None
        display_name = str(entry.get("display_name") or "").strip()
        try:
            latitude = float(entry["lat"])
            longitude = float(entry["lon"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Nominatim returned an entry without usable coordinates")
            return None
        country_code = scope if scope is not None else self._country_code(entry)
        if not display_name or country_code is None:
            logger.warning("Nominatim returned an entry with no name or no country")
            return None
        try:
            return Candidate(
                geonames_id=None,
                # The first comma-separated part is the place itself; the rest
                # is the administrative trail the display name carries.
                name=display_name.split(",")[0].strip(),
                precision=Precision.PLACE,
                country_code=country_code,
                admin1_code=None,
                admin2_code=None,
                latitude=latitude,
                longitude=longitude,
            )
        except ValidationError:
            logger.warning("Nominatim returned data outside the accepted field ranges")
            return None

    @staticmethod
    def _country_code(entry: dict[str, Any]) -> str | None:
        address = entry.get("address")
        if not isinstance(address, dict):
            return None
        country_code = address.get("country_code")
        if not isinstance(country_code, str) or len(country_code) != 2:
            return None
        # Responses report lowercase; the rest of the pipeline stores uppercase.
        return country_code.upper()
