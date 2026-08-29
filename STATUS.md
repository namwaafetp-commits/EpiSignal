# Status — where the build is right now

Small and volatile by design. The long road is in [ROADMAP.md](ROADMAP.md); the
rules for who edits this file are in
[docs/agents/workflow.md](docs/agents/workflow.md).

**Last updated:** 2026-08-29

## Position

| Field | Value |
| --- | --- |
| Band | 4 — Operations |
| Item | `M` — Manual review queue |
| Status | `building` |
| Briefing | [HANDOFF.md](HANDOFF.md) |
| Spec | [2026-08-29-manual-review-queue-design.md](docs/superpowers/specs/2026-08-29-manual-review-queue-design.md) |
| Plan | [2026-08-29-manual-review-queue.md](docs/superpowers/plans/2026-08-29-manual-review-queue.md) |

Most recently verified: parallel item `O` — High-efficiency pipeline and Gemini
transition, `verified` on 2026-08-29
([report](docs/reports/2026-08-29-subproject-o-report.md)). `E` remains the last
completed dependency on `M`'s path. `M` stays the active item and retains
`HANDOFF.md`.

The extraction stall was then fixed on `main`. Structured outputs now reach
geocoding and event assembly; the live proof recorded 28 extracted signals with
zero shape rejections, 32 geocoded signals, and the first 3 events.

## Next action

**Worker.** Read `HANDOFF.md` and the committed `M` implementation plan. Create
`codex/manual-review-queue` in a separate worktree, run a clean baseline, then
start Task 1 test-first. Set `M` to `building` in the Task 1 commit and tick each
ledger item only in the commit that completes it. Stop after Task 15 and hand
the completion report back to the planner; do not mark `M` verified.

## Parallel track `O` — high-efficiency pipeline, verified

On the operator's instruction of 2026-08-29, issue
[#1](https://github.com/namwaafetp-commits/EpiSignal/issues/1) was built in
parallel with `M`. All 14 tasks are complete. The worker gate passed at
`48da153` and is recorded in the
[report](docs/reports/2026-08-29-subproject-o-report.md). The planner
independently reran `corepack pnpm verify` at clean commit `efb80f2`: 905
Python tests passed with 1 warning, 58 web tests passed across 8 files, 211
files passed formatting, lint and types passed across 107 source files,
contracts matched, and the production build succeeded. `O` is `verified`.
This parallel verification does not retarget the active position or overwrite
`M`'s `HANDOFF.md`.

**Roster reorder, 2026-08-29, operator instruction (commit `02c23a7`):** the
active ladder is `google/gemini-3.1-flash-lite` (T1), `google/gemini-3.5-flash-lite`
(T2), `mistralai/mistral-small-24b-instruct-2501` (T3, the one OpenRouter
fallback rung). `gemini-2.5-flash-lite` is retired for new API keys — the
live API answers 404 — so 3.1 takes the everyday role; the seed keeps the
retired row inactive so it can never silently reactivate. The planner's live
10-signal climb recorded T1 on every extraction, T2 after every T1 rejection,
and T3 on all four climbs where T2 also rejected. This participation matches
the configured tier-sorted ladder, but `ai_requests` has no durable attempt
ordinal; `F` must add one rather than treat physical row order as a contract.
Classification at T1 accepted its one 10-signal batch. T1 extraction accepted
0 of 7 attempts (6 shape rejections, 1 ungrounded); T2 accepted 3 of 7; T3
accepted all 4 fallbacks. The run extracted all 7 relevant signals with no
review or unavailable result, but the Gemini-first extraction roster is not
trusted for overnight operation from this evidence.

The worker baseline below reports `ai_models=5` from the seed command; that is
the number of seed entries, not live table cardinality. The planner's read-only
check after seeding found 7 total model rows and 3 active rows: T1 Gemini 3.1,
T2 Gemini 3.5, and T3 Mistral.

`F` is the next planner recommendation after active `M`: persist acceptance,
cost-per-accepted, grounding, and brief-quality measurements by model and
purpose. Do not wire batch jobs while trailing spend remains below target. Do
not make a hidden roster change before `F` can compare a Gemini prompt fix with
purpose-specific model routing.

## Settled for `M`, so the worker does not redesign it

- Open review cases are durable records with typed reasons, not a view inferred
  forever from nullable signal fields.
- One signal has at most one open case, but every closed case remains as audit
  history.
- Cause-specific resolution either requeues the existing pipeline, finalizes
  an event through shared rules, or sets terminal `dismissed`; no evidence is
  deleted or edited.
- Event-link choices are limited to candidate IDs and match scores stored when
  deterministic matching refused.
- A single bearer token protects review reads and writes. It is entered by the
  operator and kept only in browser component memory; no account system is in
  scope.
- The new review workspace borrows the supplied console's navy structure, cyan
  selection, and dense rail/work-area composition. It reuses the current
  Fraunces/Inter, semantic CSS, Tailwind, and web shell with no UI dependency.
  `M` does not restyle the existing radar, map, or pipeline; the reference's
  severity, counts, and publishers are not product data.
- Migration downgrade refuses to erase live review history.
- Live planning evidence was 37 review rows: 28 unresolved diseases, 7
  missing-text retrieval rows, 1 content-integrity quarantine, and 1 ambiguous
  event match. Re-query before migration; never hard-code these counts.

## Task ledger

- [x] 1. Define review vocabularies and ORM shape.
- [x] 2. Add reversible schema expansion and conservative backfill.
- [x] 3. Define review commands, read models, and storage interface.
- [x] 4. Persist typed case opening, queue reads, and automatic recovery.
- [x] 5. Make every `needs_review` writer record a typed cause.
- [x] 6. Extract one event-finalization implementation.
- [x] 7. Resolve retry, disease, and dismissal cases transactionally.
- [x] 8. Resolve ambiguous event cases through shared finalization.
- [x] 9. Add secret admin authentication and safe configuration.
- [x] 10. Expose authenticated queue reads.
- [x] 11. Expose transactional resolution and regenerate contracts.
- [x] 12. Strictly validate the review API in the web client.
- [ ] 13. Build the accessible cause-specific review queue.
- [ ] 14. Mount the inspired review workspace in the existing web shell.
- [ ] 15. Review, verify, capture safe live proof, and report.

## Task ledger — `O` (parallel track)

- [x] 1. Enforce the query-rule language in the GDELT client.
- [x] 2. Pin the seed library to English.
- [x] 3. Make provider a roster fact.
- [x] 4. Build `GeminiChatModel`.
- [x] 5. Resolve rungs through provider adapters.- [x] 6. Validate Gemini live on ten to twenty real signals.
- [x] 7. Add the delta pass.
- [x] 8. Wire the delta pass after attach.
- [x] 9. Build the Gemini batch client.
- [x] 10. Route scheduled stages through the provider ladder.
- [x] 11. Build the pre-group stage.
- [x] 12. Store pre-groups and change selection.
- [x] 13. Add the measurement gate.
- [x] 14. Review, gate, and report.

## Blockers

**None.** `M` is planned and dependency-ready. Implementation has not started.

## Verified baseline

Everything below was true at commit `48da153` on `main`. Recorded from the
`O` run logged untruncated in
[docs/reports/2026-08-29-subproject-o-report.md](docs/reports/2026-08-29-subproject-o-report.md).

| Fact | Value |
| --- | --- |
| Verification command | `corepack pnpm verify` — exit code 0 |
| Python tests | 905 passed, 1 warning |
| Web tests | 58 passed, 8 files |
| Lint and format | `ruff check` and `eslint` clean, 190 files formatted |
| Types | `tsc` and `mypy` clean across 107 source files |
| Migration revision | `20260829_0013_story_groups` |
| Live database | `db:migrate` and `db:seed` applied: query_rules=62 (English-only active), ai_models=5 |
| Canonical diseases | 29 stable of 29 rows |
| Canonical sources | 2 stable and inactive |
| Extraction schema | `extraction_schema_version: 2`, 5-slot brief, English title, provider-routed structured outputs |
| Model ladder | `google/gemini-3.1-flash-lite` (T1), `google/gemini-3.5-flash-lite` (T2), `mistralai/mistral-small-24b-instruct-2501` (T3 fallback); reordered at `02c23a7` per operator instruction |
| Trailing AI spend | `spend:report` — 30 days, 139 requests, $0.118554 |
| Pre-group stage | Built, `pregroup_enabled=false`; measurement gate decided no flip |
| Radar endpoints | `GET /api/v1/radar`, `GET /api/v1/admin/pipeline-runs` |
| Live extraction proof (O) | 20 classified, 13 extracted; Gemini accepted 4, Mistral tier-2 caught all 9 rejects; run cost $0.0390 |

Reproduce with:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src packages/backend/src
corepack pnpm verify
corepack pnpm spend:report
```

Update this table only from a run you actually performed, and record the commit
it was performed at.
