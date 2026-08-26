# ECDC Epidemiological Update Ingestion — Design

**Date:** 2026-08-26
**Status:** Approved
**Depends on:** `2026-08-26-who-don-ingestion-design.md`,
`2026-08-26-signal-evidence-browser-design.md`

## Goal

Add ECDC as the second ingested source, so the evidence browser stops showing a
single publisher. The connector reads ECDC's epidemiological-update feed,
fetches each linked article, and stores the article's exact prose as evidence
under the existing versioned-signal model.

Success is a second source appearing in `GET /api/v1/signals` with a live
`source_count` of 2, every stored row carrying non-blank `raw_text` taken
verbatim from an ECDC page, and repeated runs inserting nothing new.

## Out of scope

- The weekly Communicable Disease Threats Report (CDTR). Its HTML page carries
  only a teaser; the content is a PDF. Extracted PDF text is a transformation of
  the source, which needs its own evidence argument and its own design.
- Backfill beyond the feed horizon. See "Known coverage limit".
- Outbreak landing pages, whose only text is link cards.
- Translation, event matching, extracted case counts, summaries, relevance
  scores, and every AI field. Those belong to later slices, and
  `NormalizedSignal` still must not carry them.
- Scheduling. The connector is invoked by a command, as WHO's is.

## Source of truth

ECDC publishes an RSS 2.0 feed of epidemiological updates:

```text
https://www.ecdc.europa.eu/en/taxonomy/term/1310/feed
```

Verified behaviour as of 2026-08-26:

- The response is `application/rss+xml; charset=utf-8`, with a weak `ETag`, a
  `Last-Modified` header, and `Cache-Control: public, max-age=300`.
- The root is `<rss version="2.0" xmlns:dc="..." xml:base="https://www.ecdc.europa.eu/en">`.
  The channel carries `title`, `link`, an empty `description`, and `language`.
  There is no `lastBuildDate` and no `ttl`.
- Each `<item>` has exactly `title`, `link`, `description`, `pubDate`,
  `dc:creator`, and `guid`.
- **The feed returns 10 items with no pagination parameter and no total count.**
  There is no `$skip` equivalent. WHO's paging model does not transfer.
- `<guid isPermaLink="true">` is byte-identical to `<link>` on every item, so the
  guid supplies no identifier beyond the URL.
- `<description>` is a double-escaped teaser: `<p>` arrives as `&amp;lt;p&amp;gt;`.
  It is a teaser, never the full text, and is not evidence.

The linked article pages carry the evidence. Verified on five pages:

- The body is server-rendered HTML. No client rendering, no PDF.
- Every page exposes Open Graph metadata: `og:type`, `article:published_time`
  (ISO 8601 with offset), and `og:updated_time`. There is no JSON-LD and no
  Dublin Core.
- `og:updated_time` genuinely tracks edits. On the Shigella update it is
  2026-05-26 against a publication time of 2026-05-20.
- `<link rel="canonical">` is present on every page.
- `<link rel="shortlink" href="https://www.ecdc.europa.eu/en/node/41940">`
  exposes a stable Drupal node ID on `News` and `Landing Page` pages, but **not**
  on `website` pages, whose shortlink is the URL itself.

`og:type` sorts the feed into three kinds:

| `og:type` | Items | Node ID | Body | Decision |
| --- | --- | --- | --- | --- |
| `News` | 3 | Yes | 330–1970 words of prose | Ingest |
| `website` | 4 | No | 1200–3500 words of prose | Ingest |
| `Landing Page` | 2 | Yes | Link cards only | Reject |

ECDC content is licensed **CC BY 4.0**. Reuse and redistribution are permitted
with attribution to ECDC as creator, a link to the licence, and an indication of
any modification. The evidence browser already displays the publisher name and
links to the source page, which satisfies attribution. We store text unmodified,
so no modification notice is required. The ECDC logo is excluded and is not used.

## Decisions

| Decision | Choice | Reason |
| --- | --- | --- |
| Stream | Epidemiological updates feed, HTML articles | One page carries one continuous prose body, which maps onto one signal the way a WHO DON does. The CDTR is a weekly roundup locked in a PDF. |
| Item filter | Accept `og:type` of `News` and `website`; reject `Landing Page` | The real line is a continuous prose body against link cards. `og:type` alone is not a quality filter, but combined with the observed body shape it separates evidence from navigation. |
| Backfill depth | Whatever the 10-item feed returns | The feed offers no paging. Scraping ECDC's paginated listing to reach older items adds markup coupling for history the homepage already warns is limited. |
| Identity | `url` plus `content_hash`, unchanged | Four of the seven ingested pages are rewritten in place at a static URL. The existing composite key already turns an in-place rewrite into an appended version, preserving the prior text. No schema change. |
| `external_id` | Drupal node ID where present, otherwise NULL | A fabricated identifier for `website` pages would be worse than an honest absence. |
| `published_at` | `article:published_time`, falling back to feed `pubDate` | The page states its own publication time; the feed restates it. |
| Revision signal | `content_hash` over title and body, not `og:updated_time` | `og:updated_time` is stale on `website` pages, where it equals the publication time despite in-place rewrites. Only the text decides whether the text changed. |
| Article fetch failure | Recorded in the payload, raised in `normalize` | Keeps per-document failure accounting in the pipeline where it already lives, and keeps `normalize` a pure function. See "Error handling". |
| Rejected page type | Counted as `rejected`, not `failed` | A `Landing Page` in the feed is normal and permanent. Counting it as a failure would make the command exit non-zero on every healthy run, which trains people to ignore the exit code. Counting it separately keeps the rejection visible without faking an error. |
| HTML parsing | Extend the existing stdlib `HTMLParser` approach | The backend has five runtime dependencies and no HTML library. A scoped parser is enough and adds none. |
| Placement | `ingestion/ecdc_epi.py` plus a shared `ingestion/html_text.py` | Shared code is extracted only where the second connector forces it. |

## Schema change

None. `uq_signals_url_content_hash` from revision `20260826_0002` already
supports both new-URL publication and in-place rewriting.

## Pipeline change

One narrow addition, forced by the second source. `ingestion/protocol.py` gains
an exception the connectors may raise:

```python
class UnsupportedDocument(Exception):
    """The source returned a document this connector does not ingest."""
```

`run_ingestion` catches it before the general `except Exception`, counts it in a
new `IngestionResult.rejected` field, logs the document URL and the reason at
`INFO`, and continues. It does not roll back, because nothing was written.
`failed` keeps its meaning: something went wrong. `rejected` means the source
published something outside this connector's scope, which is routine.

`ingest_runner.py` prints `rejected=` alongside the other counts and still exits
non-zero only when `failed > 0`.

WHO is unaffected: `WhoDonConnector` never raises `UnsupportedDocument`, and its
`rejected` count is always zero.

## Seed change

`database/seeds/sources.json` already contains an `ECDC` entry with
`feed_url: null`. Set:

```json
"feed_url": "https://www.ecdc.europa.eu/en/taxonomy/term/1310/feed"
```

The `name` stays `ECDC`, because seeding upserts on `sources.name` and a rename
would create a second identity row rather than correct the existing one.
`active` stays `false` in the seed; `run_ingestion` already calls
`repository.activate(source_id)` after a run.

## Architecture

```text
packages/backend/src/episignal_backend/ingestion/
  html_text.py     strip_html, strip_html_within   (new, shared)
  who_don.py       WhoDonConnector                 (imports from html_text)
  ecdc_epi.py      EcdcEpiConnector                (new)
```

`html_text.py` is created by moving `strip_html`, `_TextExtractor`, `BLOCK_TAGS`,
and `SKIPPED_TAGS` out of `who_don.py` unchanged, then adding one function:

```python
def strip_html_within(html: str, *, tag: str, attribute: str, value: str) -> str
```

which returns collapsed text from inside the first element whose attribute
matches, tracking nesting depth so a closing tag of the same name inside the
region does not end it early. The double-decode note in `strip_html` carries over
verbatim: `convert_charrefs=True` already decodes entities, and a second
`html.unescape()` would corrupt evidence.

`ecdc_epi.py` is the only new module that opens a socket. It reuses
`canonicalize_url`, `content_hash`, and the retry loop shape already proven in
`who_don.py` (three attempts, exponential backoff, retry on 429/500/502/503/504).

`documents.py`, `repository.py`, and `evidence.py` are unchanged. `protocol.py`
and `pipeline.py` take only the narrow addition described under "Pipeline
change". The connector satisfies the existing `SourceConnector` Protocol, so no
boundary moves.

## Data flow

`fetch(since, inclusive=False)` performs two hops.

1. GET the feed. Parse with `xml.etree.ElementTree`. The endpoint is a fixed
   HTTPS URL under our control, and `ElementTree` does not resolve external
   entities, so no XML parser dependency is added.
2. Filter items client-side by `pubDate` against `since`, using `>=` when
   `inclusive` is true and `>` otherwise. This mirrors the WHO operator choice.
3. For each surviving item, GET the article URL. Record on success:

   ```python
   {
       "feed": {"title": ..., "link": ..., "pubDate": ..., "creator": ...},
       "article_html": "<!doctype html>...",
   }
   ```

   On failure, record `{"feed": {...}, "article_error": "<exception class name>"}`.
   The exception message is excluded: it can contain the URL and response body,
   and payloads are stored.
4. Return one `RawDocument` per item, `source_url` set to the feed link,
   `retrieved_at` set once for the whole run.

`normalize(document)` is a pure function of that payload.

1. If `article_error` is present, raise `ValueError`.
2. Read `og:type`. If it is not `News` or `website`, raise `UnsupportedDocument`
   naming the rejected type. The pipeline counts it in `rejected`, not `failed`.
3. `url` is `<link rel="canonical">`, falling back to the feed link. The page's
   own canonical is authoritative over the feed's.
4. `canonical_url` is `canonicalize_url(url)`.
5. `title` is the feed `<title>`, collapsed by `NormalizedSignal` as WHO's is.
6. `raw_text` is `strip_html_within(article_html, tag="div", attribute="id",
   value="main-content")`, with the exact container determined during
   implementation against committed fixtures. It must exclude the global
   navigation, the badge row, the "More on this topic" cards, and the footer. A
   blank result raises, which `NormalizedSignal` also enforces.
7. `published_at` is `article:published_time`, falling back to the feed
   `pubDate`. Both carry an offset; the source's offset is preserved rather than
   converted, matching `_require_aware`.
8. `external_id` is the digits from `<link rel="shortlink">` when the href
   matches `/node/<digits>`, otherwise `None`.
9. `language` is `"en"`. The feed declares `<language>en</language>` and ECDC
   publishes these pages in English only.
10. `content_hash` is `content_hash(title, raw_text)`, unchanged.

## Known coverage limit

The feed's 10-item horizon means a `--since` older than the oldest feed item
yields silently fewer documents than the window implies. At the observed
publication rate that horizon is roughly six weeks. This is accepted for this
slice: the homepage already carries the limited-coverage warning, and the
alternative is scraping a paginated HTML listing. The limit is recorded here so a
later slice that needs deep history knows it must solve backfill separately, not
assume the connector already did.

## Error handling

- A feed request that fails after three attempts raises out of `fetch`, which
  fails the run. A source that changed shape must not report success.
- An article request that fails is carried into `normalize` as `article_error`
  and raised there, so the pipeline counts it in `failed`, logs the URL and the
  exception class, rolls back that document, and continues. Folding the failure
  away inside `fetch` would have hidden it from the count.
- A rejected `og:type` raises `UnsupportedDocument` and lands in `rejected`. It
  is logged with the URL and the offending type, so a feed that starts returning
  unexpected page types is visible without turning a healthy run red.
- `ingest_runner.py` prints counts only, and exits non-zero when `failed > 0`.

A typical run therefore reports a non-zero `rejected` count and exits zero. A
`rejected` count that jumps is the signal that ECDC changed what it publishes to
this feed.

## Testing

No test uses credentials or the network.

Committed fixtures under `packages/backend/tests/fixtures/`:

- `ecdc_epi_feed.xml` — the real feed response, trimmed to four items covering
  `News`, `website`, `Landing Page`, and one item outside the window.
- `ecdc_epi_news.html` — a real `News` article page.
- `ecdc_epi_website.html` — a real `website` overview page.
- `ecdc_epi_landing.html` — a real `Landing Page`.

`normalize` tests, against fixtures, assert:

- the exact expected `raw_text`, including that navigation, badges, the "More on
  this topic" cards, and the footer are absent;
- `external_id` is the node ID on the `News` page and `None` on the `website`
  page;
- `url` comes from `rel="canonical"` when it differs from the feed link;
- `published_at` uses `article:published_time` and keeps its offset;
- a `Landing Page` raises `UnsupportedDocument`;
- an `article_error` payload raises `ValueError`, not `UnsupportedDocument`;
- a page whose body region is empty raises.

`pipeline` tests, with the existing in-memory fakes, assert that a connector
raising `UnsupportedDocument` increments `rejected`, leaves `failed` at zero,
performs no rollback, and lets the run exit zero.

`html_text` tests assert that `strip_html_within` stops at the matching close tag
when a same-named tag is nested inside, and that the existing `strip_html`
behaviour, including the double-escaped `&amp;lt;p&amp;gt;` case, is unchanged by
the move.

`fetch` tests use `httpx.MockTransport`, the pattern already in
`test_who_don_fetch.py`, and assert:

- one `RawDocument` per in-window item, and none for out-of-window items;
- `inclusive` selects `>=` against `>`;
- an article request returning 500 three times produces a document carrying
  `article_error`, not an exception out of `fetch`;
- the retry loop sleeps between attempts and stops after three;
- `retrieved_at` is identical across every document in one run.

A `mypy` structural check confirms `EcdcEpiConnector` satisfies `SourceConnector`,
since `runtime_checkable` only compares names.

## Commands

```json
"ingest:ecdc": "uv run --package episignal-backend python -m episignal_backend.ingest_runner ecdc-epi"
```

`CONNECTORS` in `ingest_runner.py` gains `"ecdc-epi": EcdcEpiConnector`. The
`connector` argument is already `choices=sorted(CONNECTORS)`, so the new key
appears in `--help` with no further change.

Live verification, run once after implementation:

```powershell
corepack pnpm db:seed
corepack pnpm ingest:ecdc
corepack pnpm ingest:ecdc
```

The first run inserts the accepted items and reports the `Landing Page` items
under `rejected`, exiting zero. The second reports `inserted=0` with the same
`rejected` count and the accepted items now under `skipped`, proving identity
holds. `GET /api/v1/signals` then reports `source_count=2`, and the homepage
shows ECDC cards alongside WHO cards with expandable exact text.
