# Lean MVP Real-Data End-to-End Validation

**Date:** 2026-08-31
**Branch:** `codex/real-data-mvp-validation`
**Code commit at report time:** `68902d923a809c869d820e2aa424dfbc03255a82`
**Database:** shared development PostgreSQL/PostGIS; migration head verified as `20260830_0019`

## Real-data window

Requested window: `2026-08-30T00:00:00Z` → `2026-08-31T00:00:00Z`.

The existing scheduler had an older cursor and anchors discovery to run time.
The bounded command configured a 1,440-minute window and a 200-article cap, but
the discovery attempt was interrupted before its run row was committed. Its
exact effective window therefore is not recoverable from `pipeline_runs`; 58
new signals were persisted before interruption. This is recorded as a
validation deviation, not presented as proof of a clean fixed-window run.

## Funnel

| Stage | Result | Evidence |
| --- | ---: | --- |
| Raw candidates | not persisted | Discovery did not complete; no final discovery counts were written |
| New signals stored | 58 | Read-only count of signals created during validation attempt |
| Retrieval | 50 examined; 13 retrieved; 33 filtered; 4 still failing | Pipeline run `0667ae3a-88e9-45ae-8bd2-0696d554e1f8` |
| Deduplication | 16 examined; 15 primaries; 1 duplicate | Pipeline run `2b0e2ba8-be27-4943-b0ee-3d3fcd33677c` |
| Story groups | 0 pre-groups; 5 event clusters in continuation | Pre-group is existing default-off configuration; matching continuation created 5 clusters |
| Triage | 81 examined; 71 relevant; 10 filtered | Pipeline run `60d96f74-a832-49c6-a45e-6061975b2389` |
| Extraction | 30 examined; 30 accepted; 0 review | Pipeline run `c5d25e36-22a5-4081-98b9-934feb7acb1f` |
| Events | 5 created in continuation; 14 total | Five new event IDs include `EVT-05423824`, `EVT-8678FFCC`, `EVT-9D2530E7`, `EVT-9C28D6EB`, `EVT-F8A59FB0` |
| Signals attached to existing events | 0 observed | No ambiguous judge path completed |
| Observations | 5 created in continuation; 17 total | Each new event has one observation; existing `EVT-71F6E327` retains 4 observations |
| Summaries | 0 created or updated | Pipeline run `a8544b2e-f1c3-4c49-ba80-ec42524d4943`: 14 examined, 14 skipped |

The initial full-chain command was stopped after repeated GDELT failures and a
long-running discovery pass. Existing stage-only commands then completed the
downstream backlog. The failed match attempt was recorded as
`DataError`; a later zero-pending match rerun passed, but no production
ambiguous-match judgement was observed.

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

- Sample: 0 summaries available; 14 events were examined and skipped.
- Unsupported facts: not assessable because no summary was generated.
- Connected `ai_models` rows lacked an active `event_summary` model. The
  repository seed contains one, but reseeding would change production roster
  state and was intentionally not done in this validation.

## Event quality and history

- Events reviewed: 14 total, including five created during continuation.
- Suspected false merges: 0 in reviewed event/source relationships.
- Suspected false splits: 0 confirmed; evidence was insufficient for a strong
  split claim because no completed ambiguous judge path was available.
- Ambiguous matches: 0 completed judgements; no event-match-judge cost rows
  were written during validation.
- Observation history: existing `EVT-71F6E327` retains four observations with
  distinct signal IDs and report timestamps. The five newly created events each
  have one observation. No prior observation was overwritten.
- Provenance: event links retain signal IDs, source names, original titles,
  publication timestamps, and source URLs; accepted extraction source spans
  passed `check_grounding` against their own signal text.

## Cost

Validation-period AI ledger rows, from `2026-08-31T01:58:00Z` onward:

- AI requests: 132
- Total cost: `$0.075679`
- TRIAGE: 81 requests, `$0.004660`
- EXTRACTION: 46 attempts, `$0.071019`
- CLASSIFICATION: 5 requests, `$0.000000`
- EVENT_MATCH_JUDGE: 0
- EVENT_SUMMARY: 0

Configured caps were 200 discovery articles, 200 requests per AI stage, and
`$0.25` per AI stage. Observed aggregate cost stayed below the `$1.00` task
cap.

## API/UI

PASS after one trivial read-path correction required to inspect real events:

- `/health/live`: 200
- `/health/ready`: 200
- `GET /api/v1/events?limit=20`: 200, 14 events
- event detail, sources, and observations routes for `EVT-F8A59FB0`: 200
- web `/events`: 200
- web `/events/EVT-F8A59FB0`: 200

The detail query had omitted its `EventSignal.event_id` predicate and caused a
SQLAlchemy ambiguous-join 500. The correction adds an explicit
`EventSignal` source and event predicate; no product redesign was made.

## Verification

- `corepack pnpm verify`: PASS — 95 web tests, 1,196 Python tests, 0 xfails;
  formatting, lint, typecheck, contracts, and production build also passed.
- `corepack pnpm test:pipeline`: PASS — 16 tests passed, 0 xfails.
- Focused triage/API checks: PASS — 15 tests passed.

Existing warnings remained: two Python/Starlette deprecation warnings and the
known Vite configuration warnings. No test failure or unexpected xfail occurred.

## Exact commands

```text
corepack pnpm db:check
corepack pnpm db:migrate
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
corepack pnpm verify
corepack pnpm test:pipeline
```

The initial `pipeline:run` used environment-only overrides (no credentials in
the command): GDELT window 1,440 minutes, max articles 200, max requests 200,
AI cost guard `$0.25` per stage, triage limit 200, extraction limit 30.

## MVP verdict

**MVP BLOCKED**

### Top blockers

1. No active event-summary model exists in the connected database, so all 14
   summary candidates were skipped and the summary/API history requirement was
   not demonstrated.
2. GDELT discovery did not complete within the bounded run: repeated
   `GdeltUnavailable` failures and interruption left no committed raw-candidate
   funnel, and 58 new signals remained at `fetched`/pending triage.
3. The first production match attempt failed with masked `DataError`; later
   continuation succeeded only with AI enrichment disabled and produced no
   completed ambiguous-match judgement. Production match/judge behavior remains
   unproven on this data.

## Known issues

- Connected database model roster is stale versus repository seeds: no active
  Llama TRIAGE-purpose row and no active DeepSeek event-summary row. No reseed
  was performed because roster changes are out of scope.
- Triage precision needs follow-up: sample contained multiple likely false
  positives despite no obvious false negatives.
- Extraction fallback rejected 16 first attempts (12 grounding, 4 shape),
  although all 30 final stored extractions passed deterministic validation.
- API detail query correction is present on this branch and must be reviewed;
  it is not a public-surface redesign.

## Deviations

- Exact midnight-to-midnight window was requested but not recoverable because
  existing runner anchors to current time and the discovery attempt was
  interrupted before commit.
- Existing migration `20260830_0019` was applied because required
  `event_summaries` schema was absent; this created missing schema objects only.
- Downstream stage-only continuation was used after discovery interruption;
  this report does not claim a clean single-process end-to-end run.
- No production roster, routing, threshold, GDELT query, embedding setting,
  benchmark history, or public product surface was changed.
