"""Turning source HTML into evidence text.

Shared by every connector whose source publishes prose as markup. `strip_html`
flattens a fragment; `strip_html_within` flattens only the regions a page uses
for its article body, so navigation, badges and footers never reach
`signals.raw_text`.

Neither function rewrites what the source said. Tags become whitespace and
runs of whitespace collapse, because a reflowed paragraph is not a different
paragraph, but no word is dropped, added or reordered.
"""

from html.parser import HTMLParser

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


class _ScopedExtractor(HTMLParser):
    """Collects text from every region matching one tag and attribute token.

    Depth is tracked against the target tag name so a nested element of the same
    name does not end the region at its own closing tag, which would truncate the
    body mid-sentence.
    """

    def __init__(self, tag: str, attribute: str, token: str) -> None:
        super().__init__(convert_charrefs=True)
        self._tag = tag
        self._attribute = attribute
        self._token = token
        self._depth = 0
        self._skipping = 0
        self.regions: list[str] = []
        self._parts: list[str] = []

    def _matches(self, attrs: list[tuple[str, str | None]]) -> bool:
        value = dict(attrs).get(self._attribute)
        if value is None:
            return False
        # Token match rather than equality: Drupal composes class attributes from
        # several independent lists, so the body class arrives beside layout and
        # spacing classes that change without meaning anything.
        return self._token in value.split()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._depth:
            if tag == self._tag:
                self._depth += 1
            if tag in SKIPPED_TAGS:
                self._skipping += 1
            elif tag in BLOCK_TAGS:
                self._parts.append(" ")
        elif tag == self._tag and self._matches(attrs):
            self._depth = 1

    def handle_endtag(self, tag: str) -> None:
        if not self._depth:
            return
        if tag in SKIPPED_TAGS:
            if self._skipping:
                self._skipping -= 1
        elif tag in BLOCK_TAGS:
            self._parts.append(" ")
        if tag == self._tag:
            self._depth -= 1
            if self._depth == 0:
                collapsed = " ".join("".join(self._parts).split())
                if collapsed:
                    self.regions.append(collapsed)
                self._parts = []

    def handle_data(self, data: str) -> None:
        if self._depth and not self._skipping:
            self._parts.append(data)


def strip_html_within(value: str, *, tag: str, attribute: str, token: str) -> str:
    """Return the text of every `<tag>` whose `attribute` carries `token`.

    Regions are joined with a blank line, matching how `who_don` joins the
    sections WHO returns separately. An absent region yields an empty string,
    which callers treat as "this page carries no evidence" rather than as an
    empty document.
    """
    extractor = _ScopedExtractor(tag, attribute, token)
    extractor.feed(value)
    extractor.close()
    return "\n\n".join(extractor.regions)
