# GDELT Discovery Connector — Design

**Date:** 2026-08-27
**Status:** Approved
**Sub-project:** A of `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md`
**Depends on:** WHO DON and ECDC ingestion (merged to `main` on 2026-08-27)

## Goal

Discover news articles through GDELT and store each one as a signal attributed
to the publisher that actually wrote it, with its original URL, its own body
text, and four separately recorded timestamps.

This slice ends when signals exist with correct discovery provenance. It does
not filter, classify, extract, cluster, or score them.

## Out of scope

Explicitly excluded, each its own later sub-project:

- cross-syndication deduplication and rule-based filtering (B);
- every AI call, including classification, extraction, and escalation (C);
- story clustering, event matching, and the two scores (D);
- the Signal Radar API, its UI, and the admin monitoring view (E);
- the model benchmarking harness (F).

Nothing in this slice writes to `events`, `event_signals`,
`event_observations`, or `event_locations`. Nothing in it calls an AI model.

## Source of truth

GDELT serves article discovery through the DOC 2.0 API. No API key is required.

```text
https://api.gdeltproject.org/api/v2/doc/doc
```

### Verified behaviour as of 2026-08-27

A live request with `mode=ArtList`, `format=json`, `timespan=7d`,
`maxrecords=5`, `sort=datedesc` returned a JSON object with a single
`articles` key. Each article object carried exactly these fields:

```text
url  url_mobile  title  seendate  socialimage  domain  language  sourcecountry
```

Four observations from that response drive the decisions below.

**There is no publication date and no body text.** `seendate` is the only
timestamp, and it records when the GDELT crawler saw the article. The response
carries the headline but not a single sentence of the article itself.

**`seendate` is quantized to 15-minute buckets.** The returned values were
`20260825T190000Z`, `20260825T184500Z`, and `20260823T073000Z`. It is a coarse
crawler-sighting time and cannot stand in for a publication timestamp.

**`language` and `sourcecountry` are English names, not codes.** The response
contained `"Spanish"` and `"United States"`. The `signals.language` column is
`String(8)` and `country_code` is `String(2)`, so an unmapped value would be
rejected or, worse, truncated into a plausible-looking wrong code.

**Titles carry publisher furniture.** One returned title ended with an em dash,
the affiliate name, and a bracketed channel number; only the text before the
dash is the headline.

Two further observations concern volume and access.

**Syndication is severe and immediate.** Four of the five returned articles were
the same measles story republished across four Telemundo affiliates, with
identical `seendate` and near-identical URLs. This is the problem sub-project B
solves; this slice must record `domain` and `canonical_url` so that it can.

**Rate limiting is aggressive.** The second and third requests issued
immediately after the first successful one were refused at the transport layer.
The connector must throttle conservatively and treat refusal as an expected
condition rather than a failure of the run.

### Not yet verified

The `sourcelang:` and `sourcecountry:` query operators, and whether
`timespan=15min` is accepted, could not be confirmed before rate limiting took
effect. The implementation plan verifies these against the live API before the
query seed depends on them, and the seeded rules use only plain-text queries
until it does.

## Decisions

| Decision | Choice | Reason |
| --- | --- | --- |
| Pipeline | A parallel `run_discovery`, not a generalized `run_ingestion` | `run_ingestion` resolves one `source_id` per run from `connector.source_name`, which is correct for WHO and ECDC. GDELT resolves a publisher per document. Bending one pipeline to serve both would touch working official ingestion for no benefit and blur what each run means. |
| Publisher identity | One `sources` row per domain, auto-registered on first sighting | The publisher is the source. Per-domain rows give per-publisher credibility somewhere to live when sub-project D computes `evidence_score`, and keep every article from reading as "Source: GDELT". |
| Article body | Fetched from the publisher page | GDELT returns no body text, so there would otherwise be nothing for sub-project C to classify. The fetch is required regardless of the timestamp question. |
| Missing publication time | Store the signal with `published_at` NULL | Guessing from `seendate` would present crawler time as publication time and would silently corrupt the detection-lead-time metric. Dropping the article would discard exactly the local-language reporting with the worst metadata, which is what the radar exists to catch. |
| Failed page fetch | Store with `needs_review`, retry with bounded backoff | The discovery itself is evidence and must not be lost. A user can still open the original URL, and the failure stays countable in the admin view. |
| Title | Prefer the publisher page `og:title`, fall back to the GDELT title | GDELT titles carry site names and numeric furniture. The publisher's own metadata is the better headline, but a signal must never be blocked for lack of it. |
| Query rules | A table seeded idempotently from JSON | Rules are editable in the database without a deployment, reviewable in Git, and give `signals.query_rule_id` a real row to reference. |
| Trigger | A CLI command an external scheduler calls | The same shape as `pnpm ingest:who`. An in-process daemon is deployment infrastructure that does not exist yet. |
| Language and country | Explicit mapping tables, unmapped values stored NULL | A truncated `"United States"` would become `"Un"`, a wrong code indistinguishable from a right one. NULL is honest and correctable. |

## Schema change

Revision `20260827_0003`:

```text
signals    + discovered_via   vocabulary(direct | gdelt) not null default 'direct'
           + gdelt_seen_at    timestamptz null
           + first_seen_at    timestamptz not null
           + query_rule_id    uuid null fk -> gdelt_query_rules(id) on delete set null
           index on (discovered_via)
           index on (first_seen_at)

sources    + domain           text null unique

new table  gdelt_query_rules
             id           uuid pk
             rule_group   text not null
             query        text not null
             label        text not null
             language     text null
             active       boolean not null default true
             created_at   timestamptz not null
             updated_at   timestamptz not null
             unique (query, language)
```

`discovered_via` defaults to `direct` so every existing WHO and ECDC signal
keeps its meaning without a data migration.

`first_seen_at` is not `created_at`. A revised article is stored as a new signal
version with a new `created_at`, but `first_seen_at` records when EpiSignal
first saw that URL in any version and is carried forward across revisions. The
detection-lead-time metric in section 21 of the requirement document depends on
that distinction. For existing rows the migration backfills `first_seen_at` from
`retrieved_at`, which is the earliest true sighting time already recorded.

`sources.domain` is nullable because the seeded official sources have no single
domain identity, and unique because a domain resolves to exactly one publisher.

`downgrade()` drops the added columns, the index set, and the table. It does not
attempt to reconstruct `first_seen_at`.

## Architecture

```text
packages/backend/src/episignal_backend/ingestion/
  protocol.py           + DiscoveryConnector, + DiscoveryRepository
  documents.py          + DiscoveredArticle, + DiscoveredSignal
  discovery.py          run_discovery - imports neither SQLAlchemy nor httpx
  repository.py         + SqlAlchemyDiscoveryRepository
  gdelt/
    api.py              DOC 2.0 client - the only module that calls GDELT
    article.py          publisher page fetch, robots.txt, throttling
    extract.py          pure: HTML -> published_at, title, body text
    locale.py           pure: GDELT language and country names -> codes
    queries.py          query rule loading from the database
    connector.py        GdeltConnector
packages/backend/src/episignal_backend/discover_runner.py
database/seeds/gdelt_queries.json
```

`extract.py` and `locale.py` are pure functions tested against committed
fixtures, matching how `who_don.normalize` and the ECDC tests already work.
`api.py` and `article.py` are the only modules permitted to open a socket.
`discovery.py` depends only on Protocols, so the whole decision path is
exercised with in-memory fakes, no database and no network.

### Boundaries

```python
class DiscoveryConnector(Protocol):
    discovery_name: str

    def discover(
        self, rule: QueryRule, window: TimeWindow
    ) -> Sequence[DiscoveredArticle]: ...

    def retrieve(self, article: DiscoveredArticle) -> DiscoveredSignal: ...


class DiscoveryRepository(Protocol):
    def active_rules(self) -> Sequence[QueryRule]: ...

    def seen_urls(self, canonical_urls: Sequence[str]) -> frozenset[str]: ...

    def exists(self, url: str, content_hash: str) -> bool: ...

    def first_seen_at(self, canonical_url: str) -> datetime | None: ...

    def publisher_source_id(self, domain: str) -> UUID | None: ...

    def register_publisher(self, publisher: Publisher) -> UUID: ...

    def add(self, signal: DiscoveredSignal, source_id: UUID) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
```

`QueryRule`, `TimeWindow`, `Publisher`, `DiscoveredArticle`, and
`DiscoveredSignal` are all defined in `documents.py` alongside the existing
`RawDocument` and `NormalizedSignal`, as frozen Pydantic models validated at the
boundary.

`discover` returns GDELT metadata only and opens no publisher connection.
`retrieve` performs the page fetch and is called only for URLs that survived the
seen-URL check, which is what keeps the fetch volume bounded.

`seen_urls` takes the whole batch and answers in one query rather than one query
per article, because a run may present several hundred candidate URLs.

### Publisher identity

`sources.name` and `sources.base_url` are both unique and not null, so
registration must derive them deterministically:

```text
name       og:site_name when present and not already taken, else the domain
base_url   https://{domain}
domain     the GDELT domain, lowercased
language   mapped from the GDELT language name, else 'en'
```

The domain is the identity that matters; the name is a display label. When
`og:site_name` collides with an existing source, registration falls back to the
domain rather than failing, because two publishers sharing a display name is a
cosmetic problem and a lost discovery is not.

### Signals awaiting retrieval

A signal stored after a failed page fetch has no body text, but `content_hash`
is not null and `raw_text` may be. For these rows the hash is computed over the
title alone, which stays deterministic and keeps `(url, content_hash)` valid.

Retry is driven by re-reading `needs_review` signals, not by re-discovery: the
same article discovered again would hash identically and be skipped as already
seen. When a retry succeeds, the stub row is updated in place with the retrieved
title, body, and `published_at`, and its status advances to `fetched`. This is
not overwriting evidence, because a stub holds none; it is the first time the
row acquires any.

A stub that exhausts its retry budget stays `needs_review` and remains visible
in the admin view of sub-project E.

## Data flow

1. Load active query rules. If none exist, print that the rules are not seeded
   and exit 1, matching how a missing source identity is handled today.
2. For each rule, request the DOC 2.0 API with a window of
   `EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES`, waiting
   `EPISIGNAL_GDELT_REQUEST_DELAY_SECONDS` between requests. The window is wider
   than the poll interval so that scheduler jitter cannot open a gap; the
   resulting repeats are absorbed by the existing `(url, content_hash)`
   identity.
3. Canonicalize every returned URL with the existing `canonicalize_url`.
4. Ask the repository which canonical URLs are already stored, in one query.
   Drop those. This happens before any publisher connection is opened.
5. Cap the survivors at `EPISIGNAL_GDELT_MAX_ARTICLES_PER_RUN`, oldest
   `seendate` first so that a burst never starves earlier discoveries.
6. Fetch each remaining page with bounded concurrency, honouring robots.txt per
   domain with a cached fetch, a per-domain delay, and a descriptive
   User-Agent.
7. Extract `published_at`, `og:title`, and body text from the HTML. Map
   `language` and `sourcecountry` through `locale.py`.
8. Resolve the publisher by domain, registering a new `sources` row when it is
   unknown, with `is_official` false, `credibility_tier` unknown, and
   `source_type` `local_media`.
9. Compute `content_hash` over the extracted title and body, resolve
   `first_seen_at` for the canonical URL, and store the signal with
   `discovered_via` `gdelt`, its `gdelt_seen_at`, and its `query_rule_id`.

Storage and commit are per article, as in `run_ingestion`, so one bad document
cannot discard a run's work.

## Error handling

| Condition | Handling |
| --- | --- |
| GDELT refuses or times out | Retry with exponential backoff up to a bounded attempt count. On exhaustion, record the rule as failed for this run and continue to the next rule. A single failing rule does not fail the run. |
| GDELT returns malformed JSON | Treated as a failure of that rule, counted, and logged without the payload body. |
| robots.txt disallows the path | The article is skipped and counted as disallowed. This is routine, not a failure. |
| Publisher page fetch fails | The signal is stored from GDELT metadata alone with `processing_status` `needs_review` and no body text, then retried on later runs with backoff. |
| Page fetched, no publication date | The signal is stored normally with `published_at` NULL. |
| Page fetched, no usable body text | Treated as a failed fetch: `needs_review`, because sub-project C would have nothing to read. |
| Unmapped language or country | Stored NULL and counted, so a gap in the mapping table is visible rather than silent. |
| Publisher domain already registered | The existing `sources` row is reused. Registration is idempotent under concurrent runs. |

The run exits non-zero only when a failure would otherwise be invisible: every
rule failed, or the database rejected a write.

## Testing

Every test runs without credentials and without network access, matching the
existing suite.

- `extract.py` against committed HTML fixtures covering
  `og:article:published_time`, JSON-LD `datePublished`, `<time datetime>`,
  `meta[name=date]`, a page with a body but no date, and a page with no usable
  body.
- `locale.py` against the verified GDELT spellings, including an unmapped value.
- `api.py` against a committed copy of the verified live JSON response, using a
  fake transport, plus refusal and malformed-payload cases.
- `article.py` for robots.txt allow, disallow, and unreachable, and for the
  per-domain delay.
- `discovery.py` against in-memory fakes: the seen-URL check runs before any
  retrieval, the per-run cap holds, publisher registration is idempotent,
  `first_seen_at` is carried across a revision, a failed retrieval yields
  `needs_review` without aborting the run, and a later successful retry promotes
  that stub to `fetched` in place.
- Publisher registration for the `og:site_name` collision case, proving it falls
  back to the domain rather than raising.
- A migration test that the revision applies and reverses, matching
  `apps/api/tests/test_migrations.py`.

The syndication case from the verified response is committed as a fixture now,
so sub-project B has real evidence to develop against.

## Configuration

```text
EPISIGNAL_GDELT_POLL_INTERVAL_MINUTES     15
EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES      20
EPISIGNAL_GDELT_MAX_ARTICLES_PER_RUN      500
EPISIGNAL_GDELT_REQUEST_DELAY_SECONDS     5.0
EPISIGNAL_GDELT_ARTICLE_CONCURRENCY       4
EPISIGNAL_GDELT_ARTICLE_TIMEOUT_SECONDS   15.0
EPISIGNAL_GDELT_USER_AGENT                EpiSignal/0.1 (+https://episignal.org)
```

The poll interval is configuration rather than code because the scheduler that
reads it lives outside this repository.

## Commands

```powershell
pnpm db:migrate          # applies 20260827_0003
pnpm db:seed             # upserts the query rules alongside diseases and sources
pnpm discover:gdelt      # one discovery run
```

`pnpm discover:gdelt` prints counts only. Publisher payloads and the connection
string never reach stdout, matching `ingest_runner.py`.
