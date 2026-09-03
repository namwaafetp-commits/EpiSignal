"""GDELT DOC 2.0 client.

Verified against the live API on 2026-08-27: an `ArtList` response is a JSON
object with one `articles` key, and each entry carries `url`, `url_mobile`,
`title`, `seendate`, `socialimage`, `domain`, `language`, and `sourcecountry`.
There is no publication date and no body text, which is why `article.py` exists.

`seendate` is quantized to fifteen minutes and records when the GDELT crawler
saw the article. It is stored as `gdelt_seen_at` and never as `published_at`.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from time import sleep as default_sleep
from typing import Any

import httpx

from episignal_backend.ingestion.documents import DiscoveredArticle, QueryRule, TimeWindow
from episignal_backend.ingestion.gdelt.locale import country_code, language_code
from episignal_backend.ingestion.urls import canonicalize_url

logger = logging.getLogger("episignal_backend.ingestion.gdelt.api")

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
HTTP_FALLBACK_URL = "http://api.gdeltproject.org/api/v2/doc/doc"
MAX_RECORDS = 250
TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 3
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
SEEN_FORMAT = "%Y%m%dT%H%M%SZ"
WINDOW_FORMAT = "%Y%m%d%H%M%S"
# The `sourcelang:` operator wants GDELT's three-letter codes, while query
# rules carry the two-letter codes the rest of the pipeline stores. A rule
# language without an entry here still gets the result-side guard below; it
# just does not also narrow the search at the API.
LANGUAGE_OPERATOR_CODES: dict[str, str] = {
    "en": "eng",
}


class GdeltUnavailable(Exception):
    """GDELT could not be reached or kept refusing.

    Expected rather than exceptional: the API rate-limits aggressively, and one
    unreachable rule must not fail a run covering fifty others.
    """


def parse_seen_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), SEEN_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


class GdeltDocClient:
    discovery_name = "GDELT"

    def __init__(
        self,
        client: httpx.Client | None = None,
        fallback_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._fallback_client = fallback_client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._sleep = sleep
        self._https_unavailable = False

    def search(self, rule: QueryRule, window: TimeWindow) -> tuple[DiscoveredArticle, ...]:
        query = rule.query
        operator = LANGUAGE_OPERATOR_CODES.get(rule.language)
        if operator is not None:
            query = f"{query} sourcelang:{operator}"
        parameters = {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": str(MAX_RECORDS),
            "sort": "datedesc",
            "startdatetime": window.start.astimezone(UTC).strftime(WINDOW_FORMAT),
            "enddatetime": window.end.astimezone(UTC).strftime(WINDOW_FORMAT),
        }
        payload = self._request(parameters)
        entries = payload.get("articles")
        if not isinstance(entries, list):
            return ()

        articles: list[DiscoveredArticle] = []
        dropped_by_language = 0
        for entry in entries:
            article = self._article(entry, rule)
            if article is None:
                continue
            # The second half of language enforcement: the operator narrows the
            # search, this guard keeps a misreporting entry out regardless. An
            # unmapped name cannot be confirmed as the rule's language, so a
            # rule that pins one drops it rather than trusting it.
            if rule.language != "any" and article.language != rule.language:
                dropped_by_language += 1
                continue
            articles.append(article)
        if dropped_by_language:
            logger.debug("Dropped %d entries not reporting the rule language", dropped_by_language)
        return tuple(articles)

    def _article(self, entry: object, rule: QueryRule) -> DiscoveredArticle | None:
        if not isinstance(entry, dict):
            return None
        url = str(entry.get("url") or "").strip()
        title = str(entry.get("title") or "").strip()
        domain = str(entry.get("domain") or "").strip()
        seen = parse_seen_date(str(entry.get("seendate") or ""))
        if not url or not title or not domain or seen is None:
            # A partial entry names no document we could ever fetch, so there is
            # nothing to keep and nothing to review.
            return None
        return DiscoveredArticle(
            url=url,
            canonical_url=canonicalize_url(url),
            title=title,
            domain=domain,
            gdelt_seen_at=seen,
            language=language_code(str(entry.get("language") or "")),
            country_code=country_code(str(entry.get("sourcecountry") or "")),
            query_rule_id=rule.id,
        )

    def _request(self, parameters: dict[str, str]) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(MAX_ATTEMPTS):
            try:
                if self._https_unavailable:
                    response = self._fallback_client.get(
                        HTTP_FALLBACK_URL,
                        params=parameters,
                        timeout=TIMEOUT_SECONDS,
                    )
                else:
                    response = self._client.get(
                        API_URL,
                        params=parameters,
                        timeout=TIMEOUT_SECONDS,
                    )
            except httpx.TimeoutException as error:
                last_error = error
                if not self._https_unavailable:
                    self._https_unavailable = True
                    try:
                        response = self._fallback_client.get(
                            HTTP_FALLBACK_URL,
                            params=parameters,
                            timeout=TIMEOUT_SECONDS,
                        )
                    except (httpx.TimeoutException, httpx.TransportError) as fallback_error:
                        last_error = fallback_error
                    else:
                        payload = self._response_payload(response)
                        if payload is not None:
                            return payload
                        last_error = httpx.HTTPStatusError(
                            f"GDELT returned {response.status_code}",
                            request=response.request,
                            response=response,
                        )
            except httpx.TransportError as error:
                last_error = error
            else:
                payload = self._response_payload(response)
                if payload is not None:
                    return payload
                last_error = httpx.HTTPStatusError(
                    f"GDELT returned {response.status_code}",
                    request=response.request,
                    response=response,
                )

            if attempt < MAX_ATTEMPTS - 1:
                self._sleep(2.0**attempt)

        raise GdeltUnavailable("GDELT search failed") from last_error

    @staticmethod
    def _response_payload(response: httpx.Response) -> dict[str, Any] | None:
        if response.status_code in RETRY_STATUS:
            return None
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError:
            # GDELT answers an unmatched query with a bare sentence rather
            # than JSON, which means no results, not a fault.
            return {}
        return payload if isinstance(payload, dict) else {}
