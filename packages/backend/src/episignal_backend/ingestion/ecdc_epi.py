"""ECDC epidemiological update connector.

ECDC publishes an RSS feed whose `<description>` is a teaser, so the evidence
lives on the linked article page and `fetch` makes two hops: the feed, then each
article. An article request that fails is recorded in the payload rather than
raised, so the failure is counted per document by the pipeline instead of ending
the run, and `normalize` stays a pure function of stored data.

The feed returns ten items with no paging parameter and no total, so `since` is
applied client-side and history older than the feed horizon is simply not
available. See the design document.
"""

import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import sleep as default_sleep
from typing import Any
from xml.etree import ElementTree

import httpx

from episignal_backend.ingestion.documents import NormalizedSignal, RawDocument
from episignal_backend.ingestion.fingerprint import content_hash
from episignal_backend.ingestion.html_text import strip_html_within
from episignal_backend.ingestion.protocol import UnsupportedDocument
from episignal_backend.ingestion.urls import canonicalize_url

SOURCE_NAME = "ECDC"
FEED_URL = "https://www.ecdc.europa.eu/en/taxonomy/term/1310/feed"
TIMEOUT_SECONDS = 20.0
MAX_ATTEMPTS = 3
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

BODY_TAG = "div"
BODY_ATTRIBUTE = "class"
BODY_TOKEN = "wysiwyg-content"

_META_PUBLISHED = re.compile(
    r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"',
    re.IGNORECASE,
)
_LINK_CANONICAL = re.compile(
    r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"',
    re.IGNORECASE,
)
_LINK_SHORTLINK = re.compile(
    r'<link[^>]+rel="shortlink"[^>]+href="([^"]+)"',
    re.IGNORECASE,
)
_NODE_ID = re.compile(r"/node/(\d+)\s*$")


def parse_feed_date(value: str) -> datetime:
    """Parse an RFC 2822 `pubDate`, preserving the offset ECDC sends."""
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def parse_meta_date(value: str) -> datetime:
    """Parse `article:published_time`, whose offset has no colon.

    ECDC emits `2026-08-20T13:39:42+0200`, which `fromisoformat` accepts, but
    the guard stays because a naive value would otherwise fail against the
    `timestamptz` column far from where it entered.
    """
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


class EcdcEpiConnector:
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
        feed = self._request(FEED_URL).text

        documents: list[RawDocument] = []
        for item in self._items(feed):
            published = parse_feed_date(item["pubDate"])
            # `inclusive` mirrors the WHO connector's `ge` against `gt`: an
            # explicit `--since` date means "from this date", a default window
            # means "since the moment we last looked".
            in_window = published >= since if inclusive else published > since
            if not in_window:
                continue

            payload: dict[str, Any] = {"feed": item}
            try:
                payload["article_html"] = self._request(item["link"]).text
            except Exception as error:
                # The message can carry the URL and the response body, and this
                # payload is stored, so only the class name is recorded.
                payload["article_error"] = type(error).__name__

            documents.append(
                RawDocument(
                    payload=payload,
                    retrieved_at=retrieved_at,
                    source_url=item["link"],
                )
            )
        return documents

    def _items(self, feed: str) -> list[dict[str, str]]:
        root = ElementTree.fromstring(feed)
        channel = root.find("channel")
        if channel is None:
            raise ValueError("ECDC feed has no channel")

        items: list[dict[str, str]] = []
        for element in channel.findall("item"):
            link = (element.findtext("link") or "").strip()
            published = (element.findtext("pubDate") or "").strip()
            if not link or not published:
                raise ValueError("ECDC feed item has no link or no pubDate")
            items.append(
                {
                    "title": (element.findtext("title") or "").strip(),
                    "link": link,
                    "pubDate": published,
                }
            )
        return items

    def _request(self, url: str) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._client.get(url, timeout=TIMEOUT_SECONDS)
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
            else:
                if response.status_code not in RETRY_STATUS:
                    response.raise_for_status()
                    return response
                last_error = httpx.HTTPStatusError(
                    f"ECDC returned {response.status_code}",
                    request=response.request,
                    response=response,
                )

            if attempt < MAX_ATTEMPTS - 1:
                self._sleep(2.0**attempt)

        raise last_error if last_error else httpx.HTTPError("ECDC request failed")

    def normalize(self, document: RawDocument) -> NormalizedSignal:
        payload = document.payload
        item = payload.get("feed") or {}

        error = payload.get("article_error")
        if error:
            raise ValueError(f"ECDC article could not be retrieved ({error})")

        html = str(payload.get("article_html") or "")
        if not html.strip():
            raise ValueError("ECDC document has no article HTML")

        raw_text = strip_html_within(html, tag=BODY_TAG, attribute=BODY_ATTRIBUTE, token=BODY_TOKEN)
        if not raw_text.strip():
            # Not a failure: ECDC publishes index and campaign pages to this feed
            # whose only text is navigation. Storing that as evidence would put a
            # link list in a column the browser presents as the source's words.
            raise UnsupportedDocument("page carries no article body")

        link = str(item.get("link") or "").strip()
        canonical = _LINK_CANONICAL.search(html)
        # The page's own canonical wins over the feed's link, which is the value
        # the feed happened to publish rather than the one the page claims.
        url = canonical.group(1).strip() if canonical else link
        if not url:
            raise ValueError("ECDC document has no URL")

        title = str(item.get("title") or "").strip()
        if not title:
            raise ValueError("ECDC document has no title")

        published = _META_PUBLISHED.search(html)
        published_at = (
            parse_meta_date(published.group(1))
            if published
            else parse_feed_date(str(item.get("pubDate") or ""))
        )

        shortlink = _LINK_SHORTLINK.search(html)
        node = _NODE_ID.search(shortlink.group(1).strip()) if shortlink else None

        return NormalizedSignal(
            external_id=node.group(1) if node else None,
            url=url,
            canonical_url=canonicalize_url(url),
            title=title,
            raw_text=raw_text,
            published_at=published_at,
            retrieved_at=document.retrieved_at,
            language="en",
            content_hash=content_hash(title, raw_text),
        )
