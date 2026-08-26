# Signal Evidence Browser — Design

**Date:** 2026-08-26  
**Status:** Approved  
**Depends on:** WHO DON ingestion

## Goal

Make the evidence already stored in `signals` visible on the public homepage.
Every displayed report links to the publisher and shows the exact stored text.
The page must describe present coverage honestly: 12 WHO DON reports from one
source are a working ingestion proof, not usable global surveillance coverage.

## Acceptance

- `GET /api/v1/signals` returns recent stored evidence, newest first.
- Each item contains its stable identifier, source name, title, exact
  `raw_text`, source URL, publication time, and retrieval time.
- The response includes total signal and represented-source counts plus bounded
  `limit`/`offset` pagination.
- The homepage renders the reports and direct source links.
- The homepage labels the feed as limited coverage and gives the live counts.
- API failure leaves an honest unavailable state rather than fabricated data.
- Backend and web tests run without credentials or network access.

## Public seams under test

1. The HTTP response from `GET /api/v1/signals`, with its database dependency
   replaced by an in-memory value.
2. The rendered `HomeShell`, supplied with a typed evidence-feed result.
3. The server-side web fetch adapter, with `fetch` replaced in the test.

## Response shape

```json
{
  "items": [
    {
      "id": "uuid",
      "source_name": "WHO Disease Outbreak News",
      "title": "...",
      "raw_text": "exact stored evidence",
      "url": "https://publisher.example/report",
      "published_at": "2026-08-14T15:38:29Z",
      "retrieved_at": "2026-08-26T10:00:00Z"
    }
  ],
  "total": 12,
  "source_count": 1,
  "limit": 20,
  "offset": 0
}
```

`raw_text` is not summarized or rewritten. The UI may visually constrain long
text, but the value crossing the interface remains the stored evidence.

## Architecture

- A backend evidence-query module owns the SQLAlchemy query and returns a small
  immutable page value.
- An API dependency opens the session and calls that query. Tests override this
  dependency, so importing or constructing the app never connects to a database.
- The versioned route maps the page value to Pydantic response models.
- The Next.js Server Component fetches health and evidence in parallel with
  `cache: "no-store"`. The presentational shell receives plain typed props.
- Generated OpenAPI TypeScript remains the browser-side contract source.

## Explicit non-goals

- No search, filtering, maps, event matching, AI summaries, scores, case counts,
  or extracted locations.
- No signal-detail route in this slice; the original publisher page is the
  authoritative detail destination.
- No new source connector is hidden inside the read path.

## Multi-source expansion

The next ingestion program should broaden independent official coverage before
adding aggregators. Each connector remains source-specific because document
shape, revision behavior, licensing, and evidence boundaries differ.

Priority order:

1. **ECDC communicable-disease threat reports** — strong European coverage;
   requires splitting weekly multi-threat reports without losing PDF evidence.
2. **Africa CDC outbreak updates** — closes a major regional gap and preserves
   the issuing institution as the source.
3. **PAHO epidemiological alerts and updates** — official Americas coverage,
   including English/Spanish document handling.
4. **US CDC Health Alert Network and outbreak notices** — official alerts with
   clear publication/revision metadata; deduplicate overlapping CDC collections.
5. **Selected national public-health agencies** — start with agencies offering
   stable feeds or documented interfaces; prioritize geographic gaps, not raw
   volume.
6. **ReliefWeb or ProMED only after a terms/provenance review** — useful early
   warning, but aggregator licensing and original-publisher attribution must be
   verified before ingestion.

Every candidate needs a short source design verifying its official interface,
terms, paging, revision semantics, language, evidence fields, and overlap with
existing sources. Source count alone is not the target: usable coverage means
diverse geography, timely updates, and traceable original evidence.

