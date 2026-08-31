# Lean MVP Real-Data End-to-End Validation

**Date:** 2026-08-31
**Branch:** `codex/real-data-mvp-validation`
**Code commit at report time:** `a79b249b71f66485bd29b6901baa9ba50b9046c8`
**Database:** shared development PostgreSQL/PostGIS; migration head verified as `20260830_0019`

## Real-data window

Requested window: `2026-08-30T00:00:00Z` → `2026-08-31T00:00:00Z`.

The requested midnight-to-midnight interval was not completed. The repeated
bounded run completed with an exact persisted effective window of
`2026-08-30T03:26:59.784591Z` → `2026-08-31T03:26:59.784591Z` (run
`7ccedd26-073a-4b7b-b5c2-831bf1eebe50`, status `succeeded`). The scheduler's
stored cursor and run-time anchoring caused this deviation; it is not presented
as proof of the requested fixed calendar interval.

## Funnel

| Stage | Result | Evidence |
| --- | ---: | --- |
| Raw candidates | 131 | Completed bounded discovery run `7ccedd26-073a-4b7b-b5c2-831bf1eebe50`; 62 rules run, 1 `GdeltUnavailable` |
| New signals stored | 78 | Completed discovery run; 53 candidate duplicates |
| Earlier interrupted attempt | 58 new signals | Separate prior attempt; excluded from completed discovery funnel |
| Retrieval | 50 examined; 13 retrieved; 33 filtered; 4 still failing | Pipeline run `0667ae3a-88e9-45ae-8bd2-0696d554e1f8` |
| Deduplication | 16 examined; 15 primaries; 1 duplicate | Pipeline run `2b0e2ba8-be27-4943-b0ee-3d3fcd33677c` |
| Story groups | 0 pre-groups; 5 event clusters in continuation | Pre-group is existing default-off configuration; matching continuation created 5 clusters |
| Triage | 81 examined; 71 relevant; 10 filtered | Pipeline run `60d96f74-a832-49c6-a45e-6061975b2389` |
| Extraction | 30 examined; 30 accepted; 0 review | Pipeline run `c5d25e36-22a5-4081-98b9-934feb7acb1f` |
| Events | 5 created in continuation; 14 total | Five new event IDs include `EVT-05423824`, `EVT-8678FFCC`, `EVT-9D2530E7`, `EVT-9C28D6EB`, `EVT-F8A59FB0` |
| Signals attached to existing events | 0 | Matching rerun `020ed86d-5caa-4b91-b69e-497bbb4aa13f`; no pending candidates |
| Observations | 5 created in continuation; 17 total | Each new event has one observation; existing `EVT-71F6E327` retains 4 observations |
| Summaries | 14 created; 14 examined; 0 skipped | Pipeline run `f163a4e7-9f81-4e5c-8910-a8cc2874dcaa` |

The initial full-chain command was stopped after repeated GDELT failures and a
long-running discovery pass. The later bounded discovery run completed with
one rule failure but a succeeded persisted run. The initial match `DataError`
was not reproduced; the normal match rerun passed with judge wiring enabled,
but there were no pending ambiguous candidates to exercise a judgement.

## AI validation

### Triage

- First model: `mistralai/mistral-small-24b-instruct-2501`.
- Fallback unchanged: YES in code and focused tests; live fallback was not
  exercised because the connected database roster did not contain the seeded
  Llama TRIAGE row.
- Sample: 71 relevant, 10 filtered. All 10 filtered titles were visibly
  outside outbreak surveillance; no obvious false negative was found.
- Malformed/repair failures: 0; 81 accepted TRIAGE responses, 0 repair calls.
- Precision concern: several accepted relevant responses were likely false
  positives, including a satire item, a book/opinion item, vaccination policy
  items, and a veterinary screwworm prevention item. This weakens precision but
  did not produce a critical obvious-outbreak false negative in this sample.

### Extraction

- Sample: 30 accepted real extractions.
- Stored acceptance: 30/30 passed the existing extraction schema and grounding
  validator; 0 stored grounding failures; 0 stored unsupported numeric facts.
- Rejected attempts before fallback: 12 `ungrounded`, 4 `shape`; final stage
  result was 0 review and 0 unavailable.
- Manual review found no confirmed date or location error in sampled stored
  rows. Several accepted rows retained null disease/location values, which is
  safer than invention but reduced event yield.
- Live accepted extraction models: 16 Mistral responses and 14 Gemini 3.5
  Flash-Lite responses. Extraction routing was not changed.

### Event summaries

- Sample: all 14 generated summaries reviewed.
- Model: all 14 accepted with `deepseek/deepseek-v4-flash-0731`, purpose
  `event_summary`.
- Failures: 0 failed, 0 unavailable, 14 accepted.
- Unsupported facts: no repeated unsupported facts found. Numeric claims,
  dates, and locations matched the selected source briefs or latest stored
  observation. `EVT-F00791B8` carries an explicit uncertainty about whether
  regional yellow-fever figures can be attributed to Angola; no confirmed
  wrong count, date, or location was found.
- One generated narrative concerns a water/sanitation intervention rather than
  an outbreak; it accurately says no disease data was reported. This is a
  relevance-quality issue, not an invented fact.

## Event quality and history

- Events reviewed: 14 total, including five created during continuation.
- Suspected false merges: 0 in reviewed event/source relationships.
- Suspected false splits: 0 confirmed.
- Ambiguous matches: 0 candidates; no judge call was required. Judge wiring was
  enabled with `meta-llama/llama-3.1-8b-instruct` (purpose `triage`), and the
  normal matching stage completed successfully with that wiring available.
- DataError reproduction: NO. Matching run `020ed86d-5caa-4b91-b69e-497bbb4aa13f`
  completed successfully with `seen=0`; no failing constraint, column, or type
  was reproduced, so no matching fix was required.
- Observation history: existing `EVT-71F6E327` retains four observations with
  distinct signal IDs and report timestamps. The five newly created events each
  have one observation. No prior observation was overwritten.
- Provenance: event links retain signal IDs, source names, original titles,
  publication timestamps, and source URLs; accepted extraction source spans
  passed `check_grounding` against their own signal text.

## Cost

Validation-period AI ledger rows, from `2026-08-31T01:58:00Z` onward:

- AI requests: 146
- Total cost: `$0.076939`
- TRIAGE: 81 requests, `$0.004660`
- EXTRACTION: 46 attempts, `$0.071019`
- CLASSIFICATION: 5 requests, `$0.000000`
- EVENT_MATCH_JUDGE: 0
- EVENT_SUMMARY: 14 requests, `$0.001260`

Configured caps were 200 discovery articles, 200 requests per AI stage, and
`$0.25` per AI stage. Observed aggregate cost stayed below the `$1.00` task
cap.

## API/UI

PASS after the event-detail read-path correction required to inspect real
events:

- `/health/live`: 200
- `/health/ready`: 200
- `GET /api/v1/events?limit=20`: 200, 14 events
- event detail, sources, and observations routes for `EVT-F8A59FB0`: 200
- web `/events`: 200
- web `/events/EVT-F8A59FB0`: 200

The detail query had omitted its `EventSignal.event_id` predicate and caused a
SQLAlchemy ambiguous-join 500. The correction adds an explicit
`EventSignal → Signal → Source` path and event predicate; the focused
regression test is `test_event_detail_loads_sources_through_event_signal_join`.
No product redesign was made.

## Verification

- `corepack pnpm verify`: PASS — 95 web tests, 1,198 Python tests, 0 xfails;
  formatting, lint, typecheck, contracts, and production build also passed.
- `corepack pnpm test:pipeline`: PASS — 16 tests passed, 0 xfails.
- Focused triage/API checks: PASS — 15 tests passed.
- Summary serialization regression: PASS — UUID provenance IDs are stored as
  JSONB-safe strings.

Existing warnings remained: two Python/Starlette deprecation warnings and the
known Vite configuration warnings. No test failure or unexpected xfail occurred.

## Exact commands

```text
corepack pnpm db:check
corepack pnpm db:migrate
corepack pnpm db:seed
corepack pnpm pipeline:run
corepack pnpm pipeline:run -- --only retrieve
corepack pnpm pipeline:run -- --only dedupe
corepack pnpm pipeline:run -- --only triage
corepack pnpm pipeline:run -- --only pregroup
corepack pnpm pipeline:run -- --only extract
corepack pnpm pipeline:run -- --only geocode
corepack pnpm pipeline:run -- --only match
corepack pnpm pipeline:run -- --only summarize
corepack pnpm pipeline:run -- --only match
corepack pnpm pipeline:run -- --only discover
corepack pnpm pipeline:run -- --only match
uv run pytest packages/backend/tests/test_event_repository.py -k "source_signal_ids or store_summary_propagates" -q
uv run pytest packages/backend/tests/test_event_read.py -q
corepack pnpm verify
corepack pnpm test:pipeline
```

The initial `pipeline:run` used environment-only overrides (no credentials in
the command): GDELT window 1,440 minutes, max articles 200, max requests 200,
AI cost guard `$0.25` per stage, triage limit 200, extraction limit 30.

## MVP verdict

**MVP READY WITH MINOR FIXES**

### Top blockers

1. One of 62 GDELT rules returned `GdeltUnavailable`; 61 rules completed and
   the bounded discovery run persisted as `succeeded`.
2. `EVT-F00791B8` retains an explicitly disclosed uncertainty about attributing
   regional yellow-fever counts to Angola.
3. No additional blocker identified; extraction benchmarking remains deferred.

## Known issues

- Triage precision needs follow-up: sample contained multiple likely false
  positives despite no obvious false negatives; this is not an MVP blocker for
  this review.
- Extraction fallback rejected 16 first attempts (12 grounding, 4 shape),
  although all 30 final stored extractions passed deterministic validation.
- The summary JSONB provenance fix and API detail query correction are present on
  this branch with focused regression coverage.

## Deviations

- Exact midnight-to-midnight window was requested but the completed run used
  `2026-08-30T03:26:59.784591Z` → `2026-08-31T03:26:59.784591Z` because the
  existing runner anchors to its scheduler cursor and run time.
- Existing migration `20260830_0019` was applied because required
  `event_summaries` schema was absent; this created missing schema objects only.
- Downstream stage-only continuation was used after discovery interruption;
  this report does not claim a clean single-process end-to-end run.
- `corepack pnpm db:seed` synchronized the connected database to repository
  seeds; no seed files were modified. No query, architecture, threshold,
  embedding, benchmark, or public product surface was changed.
