# EpiSignal Briefing Ranking V1

Date: 2026-09-17
Status: Implemented and tested in shadow mode; not deployed.

## Architecture

- The API remains server-authoritative. It fetches dashboard events and applies
  the ranking order before returning them to the web client.
- `BRIEFING_RANKING_ENABLED=false` is the default. When enabled, the client
  preserves the API order and renders the ranked flat Briefing feed.
- The scheduled `popularity:sync` worker reads the separately hosted Umami API;
  page requests never carry the Umami server token and the dashboard API never
  calls Umami.

## Ranking

For trusted fresh metrics:

```text
recency = exp(-age_hours / 36)
score = 0.65 * recency + 0.35 * engagement_percentile
```

Engagement uses unique-session Briefing impressions and Briefing opens over a
rolling 48-hour window. CTR is Bayesian-smoothed with prior strength 20 and a
global baseline CTR. Events with fewer than 5 unique impressions receive
neutral engagement `0.50`. Ties resolve by newer report timestamp, then
ascending public event ID. Missing, malformed, future-dated, or older-than-60-
minutes metrics fall back to recency-only ordering.

## Impression tracking and privacy

The browser emits `event_impression` only for an approved public event ID after
the card remains at least 50% visible for one continuous second. It sends once
per browser session/page lifetime with only:

```json
{"event_id":"EVT-XXXXXXXX","surface":"briefing","position_bucket":"1-5"}
```

The server sync deduplicates session IDs in memory, filters to Briefing
impressions and Briefing opens, skips unknown/malformed IDs, and persists only
per-event aggregate counts and scores. Session IDs and visitor identifiers are
not stored.

## Database and migration

Previous head: `20260912_0025`
New head: `20260917_0026`
Migration: `event_popularity_metrics`

The table has one unique `(event_id, window_start, window_end)` row, foreign-key
cascade to `events`, and indexes on `event_id` and `(event_id, window_end)`.
It stores unique impression/open counts, baseline CTR, smoothed CTR,
engagement percentile, calculation time, and the exact rolling window.

## Umami contract

The adapter targets the self-hosted Umami `/api/websites/:websiteId/event-data-pivot`
endpoint with `startAt`, `endAt`, `eventName`, `page`, and `pageSize`, using a
server-only Bearer token. The repository does not pin the separately hosted
Umami version; operators must verify endpoint and authentication compatibility
before enabling the worker. See the [Umami API documentation](https://docs.umami.is/docs/api)
and [event-data documentation](https://docs.umami.is/docs/api/events).

## Verification

- `corepack pnpm verify`: formatting, lint, typecheck, web tests, Python tests,
  OpenAPI contract generation/check, and web build.
- Final passing counts: 188 web tests; 1,574 Python/API tests; 2 skipped.
- Migration head check: `20260917_0026 (head)`.
- Offline migration SQL rendered successfully.

## Operations and rollout

The worker is intended to run approximately every 15 minutes. Keep the flag
off while collecting and reviewing 24–48 hours of shadow aggregates. Enable it
only after confirming the Umami endpoint, counts, stale fallback, and ranking
quality. This implementation was **not deployed**.
