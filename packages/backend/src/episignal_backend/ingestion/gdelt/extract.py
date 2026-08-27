"""Turning a publisher's page into evidence.

GDELT reports that an article exists; it reports neither when the article was
published nor what it says. Both come from the publisher's own markup, which is
why this module exists and why it is pure: every branch below is reachable from
a committed fixture with no network access.

Parsing uses the standard library, matching `ingestion/html_text.py`. A news
page is not trusted markup, and `HTMLParser` tolerates the malformed tag soup
real publishers serve.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser

BODY_TAGS = frozenset({"p"})
EXCLUDED_TAGS = frozenset({"script", "style", "nav", "header", "footer", "aside", "form"})
DATE_META_PROPERTIES = (
    "article:published_time",
    "og:article:published_time",
    "datepublished",
    "date",
    "pubdate",
    "publish-date",
    "dc.date.issued",
)
JSON_LD_DATE_KEYS = ("datePublished", "dateCreated")


@dataclass(frozen=True)
class PageMetadata:
    title: str | None
    site_name: str | None
    published_at: datetime | None
    published_at_offset_minutes: int | None
    body: str


def parse_timestamp(value: str) -> tuple[datetime, int | None] | None:
    """Parse an ISO 8601 value, keeping the offset the publisher stated.

    The offset is returned separately because `timestamptz` normalizes to UTC
    and discards it, and the publication time a reader should see is the one the
    publisher wrote. A bare date yields no offset rather than a guessed one.
    """
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC), None
    offset = parsed.utcoffset()
    return parsed, None if offset is None else int(offset.total_seconds() // 60)


def _json_ld_dates(payload: object) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in JSON_LD_DATE_KEYS and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_json_ld_dates(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_json_ld_dates(item))
    return found


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og_title: str | None = None
        self.site_name: str | None = None
        self.document_title: str | None = None
        self.date_candidates: list[str] = []
        self.body_parts: list[str] = []
        self._excluded = 0
        self._in_body_tag = 0
        self._in_document_title = False
        self._in_json_ld = False
        self._json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): (value or "") for name, value in attrs}

        if tag == "script" and attributes.get("type", "").lower() == "application/ld+json":
            self._in_json_ld = True
            return
        if tag in EXCLUDED_TAGS:
            self._excluded += 1
            return
        if self._excluded:
            return

        if tag == "meta":
            self._read_meta(attributes)
        elif tag == "time":
            stated = attributes.get("datetime", "")
            if stated:
                self.date_candidates.append(stated)
        elif tag == "title":
            self._in_document_title = True
        elif tag in BODY_TAGS:
            self._in_body_tag += 1
            self.body_parts.append(" ")

    def _read_meta(self, attributes: dict[str, str]) -> None:
        key = (attributes.get("property") or attributes.get("name") or "").lower()
        content = attributes.get("content", "")
        if not content:
            return
        if key == "og:title":
            self.og_title = content
        elif key == "og:site_name":
            self.site_name = content
        elif key in DATE_META_PROPERTIES:
            self.date_candidates.append(content)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            self._read_json_ld("".join(self._json_ld_parts))
            self._json_ld_parts = []
            return
        if tag in EXCLUDED_TAGS:
            if self._excluded:
                self._excluded -= 1
            return
        if tag == "title":
            self._in_document_title = False
        elif tag in BODY_TAGS and self._in_body_tag:
            self._in_body_tag -= 1
            self.body_parts.append(" ")

    def _read_json_ld(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Publishers ship broken JSON-LD often enough that it must not stop
            # the rest of the page from being read.
            return
        self.date_candidates.extend(_json_ld_dates(payload))

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json_ld_parts.append(data)
            return
        if self._excluded:
            return
        if self._in_document_title:
            self.document_title = (self.document_title or "") + data
        if self._in_body_tag:
            self.body_parts.append(data)


def extract_page(html: str) -> PageMetadata:
    parser = _PageParser()
    parser.feed(html)
    parser.close()

    published_at: datetime | None = None
    offset_minutes: int | None = None
    for candidate in parser.date_candidates:
        parsed = parse_timestamp(candidate)
        if parsed is not None:
            published_at, offset_minutes = parsed
            break

    title = parser.og_title or parser.document_title
    return PageMetadata(
        title=" ".join(title.split()) if title else None,
        site_name=" ".join(parser.site_name.split()) if parser.site_name else None,
        published_at=published_at,
        published_at_offset_minutes=offset_minutes,
        body=" ".join("".join(parser.body_parts).split()),
    )
