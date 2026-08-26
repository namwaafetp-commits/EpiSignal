"""WHO Disease Outbreak News connector.

WHO publishes DONs through an OData JSON API rather than a feed. `normalize` is
a pure function of one payload, so it is tested against a committed fixture with
no network access.
"""

from datetime import UTC, datetime
from html.parser import HTMLParser

from episignal_backend.ingestion.documents import NormalizedSignal, RawDocument
from episignal_backend.ingestion.fingerprint import content_hash
from episignal_backend.ingestion.urls import canonicalize_url

SOURCE_NAME = "WHO Disease Outbreak News"
ITEM_URL_TEMPLATE = "https://www.who.int/emergencies/disease-outbreak-news/item/{url_name}"
SECTION_FIELDS = ("Overview", "Epidemiology", "Assessment", "Advice", "Response")
BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "ul",
        "ol",
        "tr",
        "td",
        "th",
        "table",
        "thead",
        "tbody",
        "section",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }
)
SKIPPED_TAGS = frozenset({"script", "style"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIPPED_TAGS:
            self._skipping += 1
        elif tag in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED_TAGS:
            if self._skipping:
                self._skipping -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append(" ")


def strip_html(value: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(value)
    extractor.close()
    # `convert_charrefs=True` already decodes entities while parsing data, so a
    # second `html.unescape()` here would decode an upstream double-escaped
    # value (e.g. `&amp;lt;`) into a literal tag and corrupt the evidence text.
    return " ".join("".join(extractor.parts).split())


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class WhoDonConnector:
    source_name = SOURCE_NAME

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
