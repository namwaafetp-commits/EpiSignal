"""WHO Disease Outbreak News connector.

WHO publishes DONs through an OData JSON API rather than a feed. `normalize` is
a pure function of one payload, so it is tested against a committed fixture with
no network access.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from time import sleep as default_sleep
from typing import Any

import httpx

from episignal_backend.ingestion.documents import NormalizedSignal, RawDocument
from episignal_backend.ingestion.fingerprint import content_hash
from episignal_backend.ingestion.html_text import strip_html
from episignal_backend.ingestion.urls import canonicalize_url

SOURCE_NAME = "WHO Disease Outbreak News"
API_URL = "https://www.who.int/api/news/diseaseoutbreaknews"
PAGE_SIZE = 50
TIMEOUT_SECONDS = 20.0
MAX_ATTEMPTS = 3
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
ITEM_URL_TEMPLATE = "https://www.who.int/emergencies/disease-outbreak-news/item/{url_name}"
SECTION_FIELDS = ("Overview", "Epidemiology", "Assessment", "Advice", "Response")

__all__ = ["API_URL", "SOURCE_NAME", "WhoDonConnector", "parse_utc", "strip_html"]


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class WhoDonConnector:
    source_name = SOURCE_NAME

    def __init__(
        self,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._sleep = sleep

    def fetch(self, since: datetime, *, inclusive: bool = False) -> Sequence[RawDocument]:
        retrieved_at = datetime.now(UTC)
        documents: list[RawDocument] = []
        skip = 0

        while True:
            items = self._page(since, skip, inclusive=inclusive)
            documents.extend(
                RawDocument(
                    payload=entry,
                    retrieved_at=retrieved_at,
                    source_url=(
                        ITEM_URL_TEMPLATE.format(url_name=entry["UrlName"].strip())
                        if isinstance(entry.get("UrlName"), str) and entry["UrlName"].strip()
                        else None
                    ),
                )
                for entry in items
            )
            if len(items) < PAGE_SIZE:
                return documents
            skip += PAGE_SIZE

    def _page(self, since: datetime, skip: int, *, inclusive: bool) -> list[dict[str, Any]]:
        moment = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        operator = "ge" if inclusive else "gt"
        parameters = {
            "$filter": (
                f"PublicationDateAndTime {operator} {moment} or LastModified {operator} {moment}"
            ),
            "$orderby": "LastModified asc",
            "$top": str(PAGE_SIZE),
            "$skip": str(skip),
        }
        payload = self._request(parameters)
        if "value" not in payload:
            raise ValueError("WHO API response has no value")
        value = payload["value"]
        if not isinstance(value, list):
            raise ValueError("WHO API response value must be a list")
        if not all(isinstance(entry, Mapping) for entry in value):
            raise ValueError("WHO API response value items must be objects")
        return [dict(entry) for entry in value]

    def _request(self, parameters: dict[str, str]) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._client.get(API_URL, params=parameters, timeout=TIMEOUT_SECONDS)
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
            else:
                if response.status_code not in RETRY_STATUS:
                    response.raise_for_status()
                    result: dict[str, Any] = response.json()
                    return result
                last_error = httpx.HTTPStatusError(
                    f"WHO API returned {response.status_code}",
                    request=response.request,
                    response=response,
                )

            if attempt < MAX_ATTEMPTS - 1:
                self._sleep(2.0**attempt)

        raise last_error if last_error else httpx.HTTPError("WHO API request failed")

    def normalize(self, document: RawDocument) -> NormalizedSignal:
        payload = document.payload

        url_name = str(payload.get("UrlName") or "").strip()
        if not url_name:
            raise ValueError("WHO document has no UrlName")

        published = str(payload.get("PublicationDateAndTime") or "").strip()
        if not published:
            raise ValueError("WHO document has no PublicationDateAndTime")

        url = ITEM_URL_TEMPLATE.format(url_name=url_name)
        title = strip_html(str(payload.get("Title") or ""))
        sections = [strip_html(str(payload.get(field) or "")) for field in SECTION_FIELDS]
        raw_text = "\n\n".join(section for section in sections if section)
        external_id = str(payload.get("DonId") or "").strip() or None

        return NormalizedSignal(
            external_id=external_id,
            url=url,
            canonical_url=canonicalize_url(url),
            title=title,
            raw_text=raw_text,
            published_at=parse_utc(published),
            retrieved_at=document.retrieved_at,
            language="en",
            content_hash=content_hash(title, raw_text),
        )
