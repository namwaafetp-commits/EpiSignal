# WHO Disease Outbreak News Ingestion — Design

**Date:** 2026-08-26
**Status:** Approved
**Depends on:** the foundation slice (`docs/superpowers/plans/2026-08-26-foundation.md`)

## Goal

Ingest WHO Disease Outbreak News documents into the `signals` table so that the
database holds real, traceable evidence for the first time. A document is stored
exactly as retrieved, keyed to the source that published it, and re-running the
ingestion never duplicates a document it has already seen.

This slice ends when signals exist. It does not interpret them.

## Out of scope

Explicitly excluded, each its own later slice:

- the ECDC connector and every other source;
- relevance classification;
- AI structured extraction;
- geocoding;
- candidate event retrieval and event matching.

Nothing in this slice writes to `events`, `event_signals`, `event_observations`,
or `event_locations`.

## Source of truth

WHO serves Disease Outbreak News through an OData JSON API rather than a feed:

```text
https://www.who.int/api/news/diseaseoutbreaknews
```

Verified behaviour as of 2026-08-26:

- `$orderby=PublicationDateAndTime desc` and `$top=N` are honoured.
- Each item carries `Id`, `DonId`, `UrlName`, `ItemDefaultUrl`,
  `PublicationDate`, `PublicationDateAndTime`, `LastModified`, `Title`, and the
  body split across `Overview`, `Epidemiology`, `Assessment`, `Advice`, and
  `Response`.
- `DonId`, `UrlName`, and `ItemDefaultUrl` agree: `2026-DON615` and
  `/2026-DON615`.
- The public document URL is
  `https://www.who.int/emergencies/disease-outbreak-news/item/{UrlName}`, which
  resolves to the published item.

The RSS URL currently stored in `database/seeds/sources.json`
(`https://www.who.int/feeds/entity/csr/don/en/rss.xml`) returns HTTP 404 and is
replaced by the API endpoint above. Seeding upserts on `sources.name`, so the
correction applies in place with no manual database edit.

## Decisions

| Decision | Choice | Reason |
| --- | --- | --- |
| Scope | WHO DON only | One document describes one outbreak, so it maps cleanly onto one signal. ECDC publishes weekly roundups covering many diseases at once, which is a different problem and deserves its own design. |
| Trigger | Manual CLI command | A command is what any scheduler would eventually call. Scheduling belongs with deployment, which does not exist yet. |
| Revisions | Append a new signal version | A revised document must not erase what the earlier version said, because observations extracted later must remain traceable to the exact text that stated them. |
| Backfill depth | Last 90 days, `--since` to go deeper | Keeps the first runs fast while the connector is still being debugged, without requiring a code change to backfill. |
| Failures | Isolate per document, fail the run | One malformed document must not block the others, and a silent success must never hide a source that changed its format. |
| Placement | `packages/backend/.../ingestion/` | Reuses the existing session factory, models, and settings. A fourth workspace member is premature for one connector. |

## Schema change

Revision `20260826_0002`:

- drop `uq_signals_url`;
- add `uq_signals_url_content_hash` unique on `(url, content_hash)`;
- update `Signal.url` in the model to drop `unique=True` and declare the
  composite constraint in `__table_args__`.

This is what makes versioned signals possible. A revised WHO document keeps the
same URL, so URL alone can no longer be the identity. `content_hash` remains
indexed for lookup.

`downgrade()` reverses both constraints. It will fail if duplicate URLs already
exist, which is correct: silently discarding stored evidence to satisfy a
narrower constraint would be worse than a failed downgrade.

## Architecture

```text
packages/backend/src/episignal_backend/ingestion/
  protocol.py      SourceConnector Protocol
  documents.py     RawDocument, NormalizedSignal
  urls.py          canonicalize_url
  fingerprint.py   content_hash
  who_don.py       WhoDonConnector — the only module that opens a socket
  repository.py    SignalRepository Protocol and its SQLAlchemy implementation
  pipeline.py      run_ingestion
packages/backend/src/episignal_backend/ingest_runner.py
```

### Boundaries

`SourceConnector` is the adapter interface the handoff document calls for:

```python
class SourceConnector(Protocol):
    source_name: str

    def fetch(self, since: datetime) -> Sequence[RawDocument]: ...

    def normalize(self, document: RawDocument) -> NormalizedSignal: ...
```

`SignalRepository` is the storage interface:

```python
class SignalRepository(Protocol):
    def source_id(self, name: str) -> UUID | None: ...

    def exists(self, url: str, content_hash: str) -> bool: ...

    def add(self, signal: NormalizedSignal, source_id: UUID) -> None: ...

    def latest_published_at(self, source_id: UUID) -> datetime | None: ...

    def activate(self, source_id: UUID) -> None: ...
```

`pipeline.py` imports neither SQLAlchemy nor `httpx`. It depends on those two
Protocols and nothing else, so the whole ingestion decision path is exercised in
unit tests with an in-memory fake repository and a fake connector, needing no
database and no network. This matches the existing suite, where every test runs
without credentials.

`who_don.py` is the only module allowed to make a request. `normalize` is a pure
function of its input document, so it is tested against a committed JSON fixture.

## Data flow

1. Resolve the `Source` row by name `WHO Disease Outbreak News`. If it is
   missing, print `Run pnpm db:seed first.` and exit 1.
2. Resolve the window start: the `--since` argument if given; otherwise the
   newest `published_at` already stored for that source; otherwise 90 days before
   the run start.
3. Fetch, ascending by `PublicationDateAndTime`, paging until exhausted. An
   explicit `--since` is inclusive, so a stated date ingests that day; a window
   start derived from stored rows is exclusive, so the newest stored document
   is not refetched. Timeout 20 seconds per request, three
   retries with exponential backoff on timeouts and 5xx responses. A 4xx other
   than 429 is not retried.
4. Normalize each document into a `NormalizedSignal`:

   | Field | Value |
   | --- | --- |
   | `url` | `https://www.who.int/emergencies/disease-outbreak-news/item/{UrlName}` |
   | `canonical_url` | `canonicalize_url(url)` |
   | `external_id` | `DonId` |
   | `title` | `Title`, whitespace-collapsed |
   | `raw_text` | `Overview`, `Epidemiology`, `Assessment`, `Advice`, `Response` joined with blank lines, HTML tags stripped, entities decoded |
   | `published_at` | `PublicationDateAndTime`, UTC |
   | `retrieved_at` | run start, UTC |
   | `language` | `en` |
   | `content_hash` | `content_hash(title, raw_text)` |
   | `signal_type` | `unknown` |
   | `processing_status` | `fetched` |

   `summary`, `relevance_score`, `public_health_relevant`, `ai_extraction`,
   `ai_model`, and `ai_processed_at` stay null. They belong to the extraction
   slice, and writing a placeholder into them would be a fabricated value.

5. Skip the document when `(url, content_hash)` already exists. Otherwise insert.
   A revised document therefore lands as an additional row rather than
   overwriting the earlier text.
6. Commit each document individually, so a crash never discards work already
   done.
7. On a run that fetched successfully, set `sources.active = true`. The seeds
   ship the source inactive precisely so that a connector is what activates it.
8. Print counts only: `inserted=N skipped=N failed=N`.

### canonicalize_url

Lower-case the scheme and host, drop the fragment, drop `utm_*`, `gclid`, and
`fbclid` query parameters, sort the remaining parameters, and strip a trailing
slash from a non-empty path. Path case is preserved, because `2026-DON615` is
case-sensitive on WHO's server.

### content_hash

SHA-256 over `title` and `raw_text` after whitespace normalization, hex-encoded.
Sixty-four characters, which is exactly the width of the existing
`signals.content_hash` column. Whitespace normalization prevents a
reformatting-only edit from registering as a new version.

## Error handling

| Condition | Behaviour |
| --- | --- |
| Source row missing | Message naming `pnpm db:seed`, exit 1, nothing fetched |
| Network or HTTP failure after retries | Run fails, exit 1 |
| Document fails to normalize or insert | Log its URL, skip it, continue, exit 1 at the end |
| Nothing new to fetch | `inserted=0 skipped=0 failed=0`, exit 0 |

The window start is derived from stored rows rather than from a separate
watermark, so a failed run cannot advance past a gap. There is no state to
repair after a crash.

No log line contains the connection string, and per-document failures log the
document URL rather than its body.

## Testing

Test-first, following the existing suite's conventions.

**Pure unit tests, no network, no database**

- `canonicalize_url`: a table of inputs covering fragments, tracking parameters,
  parameter ordering, trailing slashes, and case handling.
- `content_hash`: stable across whitespace-only differences, different for
  different text, always 64 characters.
- `WhoDonConnector.normalize`: against a committed WHO API response fixture under
  `packages/backend/tests/fixtures/who_don_sample.json`, asserting every mapped
  field, HTML stripping, and UTC handling.

**Pipeline tests with fakes**

- an unseen document is inserted;
- the identical document on a second run is skipped;
- a revised document with the same URL inserts a second row;
- one malformed document does not stop the others, and the run reports it as
  failed;
- a missing source row aborts before any fetch;
- a successful run activates the source.

**Live verification, manual**

Run `pnpm ingest:who` twice against the configured Supabase project. The first
run inserts, the second must report `inserted=0`. `episignal_backend.schema_check`
gains a signal count per source so the result is visible without writing SQL.

## Commands

```powershell
pnpm db:migrate        # apply 20260826_0002
pnpm db:seed           # corrects the WHO feed URL in place
pnpm ingest:who        # last 90 days
pnpm ingest:who -- --since 2026-01-01
```

`ingest:who` maps to
`uv run --package episignal-backend python -m episignal_backend.ingest_runner who-don`.
