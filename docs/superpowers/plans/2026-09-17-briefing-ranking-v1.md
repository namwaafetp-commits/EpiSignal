# EpiSignal Briefing Ranking V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a privacy-preserving, server-authoritative Briefing ranking pipeline that runs in shadow mode by default, with real impression tracking and a resilient 48-hour Umami aggregation job.

**Architecture:** Keep the current dashboard read path as the sole Briefing data seam. Add a pure ranking module that consumes event timestamps and persisted aggregate metrics, a server-only Umami event-data-pivot adapter used only by a scheduled sync command, and one `event_popularity_metrics` table keyed to internal events. The API reads only local aggregates; the web app receives the already ordered list plus a non-secret `ranking_enabled` indicator and uses one flat card list when enabled.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, httpx, pytest, FastAPI, Next.js App Router, React, TypeScript, Vitest, Testing Library, Umami self-hosted API.

**Spec:** User-provided Briefing Ranking V1 task brief pasted in `C:\Users\DELL\.codex\attachments\2098e051-51b5-4a6d-b3de-5f2b52214598\pasted-text.txt`.

## Global Constraints

- `BRIEFING_RANKING_ENABLED=false` remains the default and preserves chronological behavior.
- Impression payloads contain only `event_id`, `surface: "briefing"`, and the coarse position bucket.
- Ranking uses only Briefing impressions and `briefing_event_open`; other analytics events remain excluded.
- Popularity uses a rolling 48-hour window and unique Umami session IDs processed in memory only.
- `RECENCY_WEIGHT=0.65`, `ENGAGEMENT_WEIGHT=0.35`, `RECENCY_TAU_HOURS=36`, `PRIOR_STRENGTH=20`, `POPULARITY_WINDOW_HOURS=48` are named constants.
- Stale or unavailable analytics fall back to 100% recency ordering; stale threshold is 60 minutes.
- Exactly one migration follows actual head `20260912_0025`; no deployment is performed.
- No epidemiological priority, personalization, lifetime popularity, cookies, or unrelated redesign is added.

---

### Task 1: Add pure ranking and popularity math

**Files:**
- Create: `packages/backend/src/episignal_backend/briefing/__init__.py`
- Create: `packages/backend/src/episignal_backend/briefing/ranking.py`
- Test: `packages/backend/tests/test_briefing_ranking.py`

**Interfaces:**
- Consumes: `BriefingEventForRanking`, `PopularityMetricForRanking`, and UTC `datetime` values.
- Produces: `recency_score`, `calculate_baseline_ctr`, `smooth_ctr`, `percentile_scores`, and `rank_briefing_events` pure functions for query and sync layers.

- [ ] **Step 1: Write failing tests for constants, recency, smoothing, baseline, and safe numeric handling.**

  The tests must assert the independent specification values: age 0 returns `1.0`, 24 hours is approximately `0.5134`, future timestamps never exceed `1.0`, invalid/missing timestamps return `0.0`, baseline `40/100` is `0.4`, and `(1 + 20 * 0.4) / (1 + 20)` is the one-impression smoothed value. Include zero-impression and non-finite input cases.

- [ ] **Step 2: Run `uv run pytest packages/backend/tests/test_briefing_ranking.py -q` and confirm the failure is caused by missing ranking functions.**

- [ ] **Step 3: Implement the named constants and minimal pure functions in `ranking.py`.**

  Define `RECENCY_WEIGHT = 0.65`, `ENGAGEMENT_WEIGHT = 0.35`, `RECENCY_TAU_HOURS = 36.0`, `PRIOR_STRENGTH = 20.0`, `POPULARITY_WINDOW_HOURS = 48`, `METRICS_STALE_AFTER_MINUTES = 60`, and `MIN_EXPOSURES_FOR_ENGAGEMENT = 5`. Clamp all scores to `[0.0, 1.0]`, treat naive datetimes as UTC, clamp future age to zero, and return baseline `0.0` for zero/invalid denominators.

- [ ] **Step 4: Write failing tests for deterministic percentile ties and neutral insufficient exposure.**

  Test one eligible value returns `0.5`, all equal values return `0.5`, `[0.1, 0.2, 0.2, 0.9]` assigns equal mid-ranks to the tied values, insufficient/no exposure returns `0.50`, and every output is within `[0.0, 1.0]`.

- [ ] **Step 5: Implement deterministic mid-rank percentile conversion and event metric calculation.**

  `percentile_scores(values)` must sort values with original-index tie preservation, use average zero-based rank divided by `n - 1`, and use `0.5` when `n <= 1`. `engagement_scores` must leave events below `MIN_EXPOSURES_FOR_ENGAGEMENT` neutral and percentile only sufficiently exposed smoothed CTR values.

- [ ] **Step 6: Write failing tests for final ranking and fallback.**

  Assert newer events win equal-popularity ties, an older higher-engagement event can win when the weighted score is higher, very old events do not win solely from engagement, missing/stale/malformed metrics produce recency-only order, ranking ties use timestamp descending then public ID ascending, ranking stays in `[0.0, 1.0]`, and disabled ranking returns the input chronological order unchanged.

- [ ] **Step 7: Implement `rank_briefing_events` with one authoritative sort path.**

  In enabled mode, validate metric timestamps and scores, use recency-only ranking when no trusted metric exists, otherwise apply `0.65 * recency + 0.35 * engagement`, and sort by score descending, canonical timestamp descending, and `public_id` ascending. In disabled mode return a tuple preserving input order. Do not put ranking math in JSX or SQL.

- [ ] **Step 8: Run the focused ranking tests and refactor only while green.**

  Run `uv run pytest packages/backend/tests/test_briefing_ranking.py -q` and require all tests to pass.

### Task 2: Add privacy-safe event impressions with visibility timing

**Files:**
- Modify: `apps/web/src/lib/analytics.ts`
- Modify: `apps/web/src/lib/analytics.test.tsx`
- Modify: `apps/web/src/components/briefing-feed.tsx`
- Modify: `apps/web/src/components/briefing-feed.test.tsx`

**Interfaces:**
- Consumes: the existing `trackEvent` boundary and `DashboardEvent.public_id`.
- Produces: the `event_impression` analytics event, `positionBucket(position)`, and one `IntersectionObserver`-backed card impression hook.

- [ ] **Step 1: Add failing analytics-boundary tests.**

  Extend the approved event list and assert a valid impression sends exactly `{ event_id, surface: "briefing", position_bucket }`, rejects invalid IDs without calling Umami, rejects invalid surfaces/buckets, and never includes headline, summary, article text, URL, or other unapproved keys.

- [ ] **Step 2: Run `corepack pnpm --filter @episignal/web exec vitest run src/lib/analytics.test.tsx` and confirm the new expectations fail.**

- [ ] **Step 3: Implement the smallest analytics additions.**

  Add the event type and approved bucket values. Make `event_impression` require `publicEventIdValue`, exact `surface === "briefing"`, and one of `"1-5" | "6-10" | "11-20" | "21+"`; invalid impressions return `null` from sanitization and are not sent. Keep existing event behavior unchanged.

- [ ] **Step 4: Add failing component tests for observer timing and deduplication.**

  Install a controllable `IntersectionObserver` test double and fake timers. Cover below 50% visibility, visible for less than one second, visible continuously for one second, leaving before one second cancels the timer, scrolling back after success does not duplicate, rerenders do not duplicate, separate valid events each emit once, all four position buckets, and malformed public IDs emit nothing.

- [ ] **Step 5: Run the focused Briefing component tests and confirm the observer behavior fails before implementation.**

  Run `corepack pnpm --filter @episignal/web exec vitest run src/components/briefing-feed.test.tsx`.

- [ ] **Step 6: Implement the visibility hook and card wiring.**

  Observe each card with threshold `0.5`; start a one-second timer only when `isIntersecting` and `intersectionRatio >= 0.5`; clear it below the threshold; after firing, add the public ID to a module-level page-session set and send the coarse position bucket. Disconnect and clear timers on unmount. Pass the canonical input position into both the existing dated/shelf rendering and the new flat rendering.

- [ ] **Step 7: Run the two focused web suites and the existing analytics suite.**

  Require all impression and legacy analytics tests to pass with no live Umami dependency.

### Task 3: Add the aggregate model and exactly one migration

**Files:**
- Create: `packages/backend/src/episignal_backend/models/popularity.py`
- Modify: `packages/backend/src/episignal_backend/models/__init__.py`
- Create: `database/migrations/versions/20260917_0026_event_popularity_metrics.py`
- Test: `packages/backend/tests/test_popularity_model.py`

**Interfaces:**
- Consumes: the existing `Event.id` internal foreign-key convention and migration head `20260912_0025`.
- Produces: `EventPopularityMetric` with safe aggregate-only persistence and indexes for event/latest-window lookup.

- [ ] **Step 1: Write failing model/migration tests.**

  Assert the mapped table is `event_popularity_metrics`, contains only event/window/count/score/calculated fields, has an event foreign key with cascade delete, a unique `(event_id, window_start, window_end)` constraint, and indexes on `event_id` and `(event_id, window_end)`. Assert the migration revision is `20260917_0026`, its `down_revision` is `20260912_0025`, and no other migration file is added.

- [ ] **Step 2: Run `uv run pytest packages/backend/tests/test_popularity_model.py -q` and confirm the expected model/migration symbols are absent.**

- [ ] **Step 3: Implement the SQLAlchemy model and export it through `models.__init__`.**

  Use UUID `event_id`, UTC timezone-aware `window_start`, `window_end`, and `calculated_at`, integer `impressions_unique` and `briefing_opens_unique`, and nullable/validated `baseline_ctr`, `smoothed_ctr`, and `engagement_score` floats. Do not add visitor/session columns or duplicated event content.

- [ ] **Step 4: Implement the one Alembic migration with reversible upgrade/downgrade.**

  Create only the new table, constraints, foreign key, and indexes; downgrade drops only this table. Verify the migration chain has one head and renders offline SQL without contacting the database.

- [ ] **Step 5: Run model tests plus `uv run alembic -c database/alembic.ini heads` and offline migration rendering.**

### Task 4: Add server-side ranking to the dashboard read path

**Files:**
- Modify: `packages/backend/src/episignal_backend/events/read.py`
- Modify: `apps/api/src/episignal_api/dependencies.py`
- Modify: `apps/api/src/episignal_api/routes/events.py`
- Modify: `apps/web/src/lib/api-dashboard.ts`
- Modify: `apps/web/src/lib/event-filters.ts`
- Modify: `apps/web/src/components/home-shell.tsx`
- Modify: `apps/web/src/components/briefing-feed.tsx`
- Test: `packages/backend/tests/test_event_read.py`
- Test: `apps/api/tests/test_events_api.py`
- Test: `apps/web/src/components/home-shell.test.tsx`
- Test: `apps/web/src/components/briefing-feed.test.tsx`

**Interfaces:**
- Consumes: `rank_briefing_events`, `EventPopularityMetric`, and the `BRIEFING_RANKING_ENABLED` settings value.
- Produces: one API response with locally ranked items and `ranking_enabled`, plus a flat Briefing renderer when that field is true.

- [ ] **Step 1: Add failing backend read-path tests.**

  Assert the dashboard still uses chronological event order with ranking disabled, performs one bulk popularity lookup when enabled, orders by ranking score/timestamp/public ID, leaves missing metrics neutral, falls back to recency for stale/malformed metrics, preserves disease/host filtering, and makes no Umami/network call.

- [ ] **Step 2: Add failing API/UI flag tests.**

  Assert the API response exposes `ranking_enabled` without exposing credentials or ranking internals, flag OFF keeps the existing dated/shelf behavior, and flag ON renders one flat ordered list with disease/location/host/recency metadata and no disease-group sections.

- [ ] **Step 3: Run the focused backend/API/web tests and confirm they fail for the missing flag and ranking behavior.**

- [ ] **Step 4: Integrate one bulk metric lookup in `query_dashboard_events`.**

  Keep the existing eligibility query and filters, build dashboard items once, fetch the latest metric row per event in one query ordered by event and window end, convert rows to ranking DTOs, and call `rank_briefing_events` exactly once. Leave the disabled path's existing SQL chronological order untouched.

- [ ] **Step 5: Wire the server setting through the API dependency and response model.**

  Read `get_settings().briefing_ranking_enabled` in the dependency, pass it into the query, and return the boolean only. Add a defaulted field so existing fakes/tests remain compatible.

- [ ] **Step 6: Preserve client filter semantics without re-sorting ranked responses.**

  Add an optional preserve-order argument to `filterEvents`; retain chronological sorting when ranking is disabled, preserve API order when `ranking_enabled` is true, and pass `ranked` to `BriefingFeed`. The current URL/history filter behavior remains intact.

- [ ] **Step 7: Implement the flat ranked renderer and run focused tests.**

  Render the same existing card component in input order when ranked; keep the old dated timeline and disease shelves only when ranking is disabled. Do not change event detail, map, or card visual design beyond the necessary container semantics.

### Task 5: Add the Umami adapter and 48-hour aggregation job

**Files:**
- Create: `packages/backend/src/episignal_backend/briefing/umami.py`
- Create: `packages/backend/src/episignal_backend/briefing/popularity_sync.py`
- Create: `packages/backend/src/episignal_backend/popularity_runner.py`
- Modify: `packages/backend/src/episignal_backend/config.py`
- Modify: `package.json`
- Modify: `.env.example`
- Modify: `.env.production.example`
- Modify: `apps/api/.env.example`
- Test: `packages/backend/tests/test_umami.py`
- Test: `packages/backend/tests/test_popularity_sync.py`
- Test: `packages/backend/tests/test_config.py`

**Interfaces:**
- Consumes: current Umami event-data-pivot API contract, approved analytics event names/properties, and valid `Event.public_id` values.
- Produces: `UmamiClient.fetch_event_records`, in-memory unique session aggregates, idempotent metric upsert, and `python -m episignal_backend.popularity_runner` / `pnpm popularity:sync`.

- [ ] **Step 1: Add failing Umami adapter tests.**

  Mock `GET /api/websites/{website_id}/event-data-pivot` responses and assert the adapter sends `startAt`, `endAt`, `eventName`, page, and page size with an `Authorization: Bearer` header; paginates; accepts the documented `{data, count, page, pageSize}` shape; rejects malformed responses; and never logs or returns raw payloads in operational summaries.

- [ ] **Step 2: Run `uv run pytest packages/backend/tests/test_umami.py -q` and confirm the adapter is missing.**

- [ ] **Step 3: Implement the server-only Umami client.**

  Use `httpx.Client` with a bounded timeout, normalize the configured base URL to the `/api` root without duplicating path segments, send the Bearer token, parse only event name, session ID, and approved property keys/values, and raise typed operational errors on HTTP/timeout/schema failures.

- [ ] **Step 4: Add failing aggregation tests for filtering, uniqueness, validation, smoothing, and zero data.**

  Cover successful mixed impression/open records, duplicate records in one session, impression surface filtering, malformed/unknown public IDs, missing session IDs, zero impressions/opens, baseline and Bayesian smoothing, neutral insufficient exposure, percentile ties, HTTP failure, timeout, malformed response, and no raw session/visitor IDs in persisted rows.

- [ ] **Step 5: Implement `sync_event_popularity`.**

  Compute `[now - 48h, now]` in UTC, load valid public IDs once, fetch only `event_impression` and `briefing_event_open`, aggregate unique `(event, session)` pairs in memory, calculate global baseline and per-event smoothed/percentile scores, set `calculated_at`, and upsert one row per known event/window. Log only window bounds, counts, skipped-invalid count, duration, and status. On any Umami failure, log a failure summary and leave the last local metrics untouched.

- [ ] **Step 6: Implement the CLI and configuration aliases.**

  Add `BRIEFING_RANKING_ENABLED=false`, `UMAMI_BASE_URL`, `UMAMI_WEBSITE_ID`, `UMAMI_API_TOKEN`, and an optional timeout using the repo’s settings validation; accept `EPISIGNAL_` aliases only for compatibility, never expose secrets as `NEXT_PUBLIC_*`, and add `popularity:sync` to `package.json`. The CLI must return nonzero on sync failure without printing secrets.

- [ ] **Step 7: Run the focused sync/config tests.**

  Require all mocked aggregation tests to pass without live Umami or a live database.

### Task 6: Persist metrics safely and wire scheduler documentation

**Files:**
- Modify: `packages/backend/src/episignal_backend/briefing/popularity_sync.py`
- Modify: `docs/architecture/scheduling.md`
- Modify: `docs/operations/umami.md`
- Create: `docs/reports/2026-09-17-briefing-ranking-v1-report.md`

**Interfaces:**
- Consumes: the model, sync service, CLI, and API behavior from Tasks 1–5.
- Produces: documented 15-minute operational scheduling guidance, API/version limitation, ranking formula, shadow-mode rollout, and completion evidence.

- [ ] **Step 1: Add a failing repository/upsert test.**

  Assert a repeated sync for the same event and window updates the existing aggregate rather than inserting a duplicate and that no raw session/visitor identifier is an attribute or SQL value.

- [ ] **Step 2: Implement a PostgreSQL-safe `ON CONFLICT` upsert and transaction boundary.**

  Use the unique event/window constraint, commit all aggregate rows together, roll back on failure, and keep prior metrics available for the API fallback path.

- [ ] **Step 3: Document the scheduler command at approximately 15-minute cadence.**

  Extend the existing scheduler guide with the command, proposed Windows Task Scheduler/cron cadence, server-only environment, and operational log fields. Do not change the existing daily pipeline schedule.

- [ ] **Step 4: Document the Umami API contract and limitation.**

  State that this checkout contains no Umami server/version, the implementation targets the current official self-hosted `/api/websites/:websiteId/event-data-pivot` contract with Bearer auth, unique session IDs are used in memory, and the deployment operator must verify the endpoint contract/version before enabling the job.

- [ ] **Step 5: Write the completion report with exact constants, failure behavior, migration head/ID, test counts, and explicit `NOT DEPLOYED`.**

### Task 7: Full verification, review, commit, and push

**Files:**
- Modify: `STATUS.md` only for the worker task ledger and fresh verified baseline, if repository workflow requires it.

- [ ] **Step 1: Run focused backend, API, and web suites plus migration checks.**

- [ ] **Step 2: Run `corepack pnpm verify` from the repository root and record the real output.**

  Do not claim completion if it fails; distinguish task-caused failures from pre-existing failures and fix task-caused failures.

- [ ] **Step 3: Inspect `git diff`, migration file list, and secret-bearing files.**

  Confirm exactly one new migration, no credentials, no unrelated changes, no deployment files, and no private analytics fields.

- [ ] **Step 4: Review the diff against `a881ed3` using the repository code-review workflow and resolve actionable findings.**

- [ ] **Step 5: Commit with `feat(briefing): add engagement-aware ranking in shadow mode`.**

- [ ] **Step 6: Push the existing `codex/next-iteration` branch to `origin`.**

- [ ] **Step 7: Run final `git status --short --branch` and report the commit hash and push status.**
