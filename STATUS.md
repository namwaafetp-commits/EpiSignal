# Status — where the build is right now

Small and volatile by design. The long road is in [ROADMAP.md](ROADMAP.md); the
rules for who edits this file are in
[docs/agents/workflow.md](docs/agents/workflow.md).

**Last updated:** 2026-08-29

## Position

| Field | Value |
| --- | --- |
| Band | 3 — GDELT layer |
| Item | `O2` — Pipeline funnel v2 |
| Status | `planned` |
| Briefing | [HANDOFF.md](HANDOFF.md) |
| Spec | [2026-08-29-pipeline-funnel-v2-design.md](docs/superpowers/specs/2026-08-29-pipeline-funnel-v2-design.md) |
| Plan | [2026-08-29-pipeline-funnel-v2.md](docs/superpowers/plans/2026-08-29-pipeline-funnel-v2.md) |

Most recently verified: parallel item `O` — High-efficiency pipeline and Gemini
transition, `verified` on 2026-08-29
([report](docs/reports/2026-08-29-subproject-o-report.md)). `E` remains the last
completed dependency on `M`'s path. `M` stays the active item and retains
`HANDOFF.md`.

The extraction stall was then fixed on `main`. Structured outputs now reach
geocoding and event assembly; the live proof recorded 28 extracted signals with
zero shape rejections, 32 geocoded signals, and the first 3 events.

## Next action

**Worker.** Read `HANDOFF.md` and the committed `O2` implementation plan. Create
`codex/pipeline-funnel-v2` in a separate worktree **from the head of
`codex/manual-review-queue`**, copy `apps/api/.env` across, run a clean
baseline, then start Task 1 test-first. Set `O2` to `building` in the Task 1
commit and tick each ledger item only in the commit that completes it. Stop
after Task 19 and hand the completion report back to the planner; do not mark
`O2` verified.

`M` — Manual review queue is `verified` on 2026-08-29 at commit `5163130`
([report](docs/reports/2026-08-29-subproject-m-report.md)). Its briefing is
archived at [docs/handoffs/2026-08-29-m.md](docs/handoffs/2026-08-29-m.md) and
`HANDOFF.md` is retargeted to `O2`.

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

## Settled for `O2`, so the worker does not redesign it

- The gate reuses `filter_rules` with a new `title_inclusion` rule group. There
  is no new table. Disease names are read from the `diseases` table, never
  copied into the seed.
- The gate is biased to pass: an empty rule set passes every title.
- `filtered` is terminal and preserves the row. Nothing is ever deleted.
- `processing_status` is a CHECK constraint, not a pg enum. The migration drops
  and recreates it, as `20260829_0014` did for `dismissed`.
- `retrieve` and `pregroup` become chain stages. Retrieval must precede dedupe,
  because dedupe compares bodies and is the only writer of `normalized`.
- `stubs_awaiting_retrieval` gains a `needs_review` status filter, and the
  pre-group deferral exclusion moves to `awaiting_extraction`. Both are
  load-bearing; without them the saving silently disappears.
- Cluster extraction stores on the representative and marks members
  `duplicate`. Every claim cites a `source_index` and is validated against that
  member's text only. Per-article extraction is the one-member case.
- The extraction schema version moves to 3; the backfill floor stays at 2.
- No new configuration flag. `pregroup_enabled=false` is the rollback lever.
- Eight corrections to the approved design are recorded in the spec's
  **Corrections** table with the file and line that forced each one. Do not
  re-derive or relitigate them.

## Task ledger — `R` (active)

- [x] 1. Normalized title.
- [x] 2. Triage vocabulary and schema columns.
- [x] 3. Purpose-scoped ladder.
- [x] 4. The triage contract.
- [x] 5. The triage prompt.
- [x] 6. The triage pass.
- [x] 7. Pre-fetch normalized-title dedup.
- [x] 8. The `triage` stage and Phase A checkpoint.
- [x] 9. pgvector and the embedding column.
- [x] 10. The embedding provider.
- [x] 11. The embedding pass and stage.
- [x] 12. Candidate blocking.
- [ ] 13. Similarity as an additive term.
- [ ] 14. Wire similarity into assembly, with decision logging.
- [ ] 15. The four calibration fixtures.
- [ ] 16. Phase B checkpoint.
- [ ] 17. The summary history table.
- [ ] 18. The event summary contract.
- [ ] 19. Representative article selection.
- [ ] 20. Material-update detection.
- [ ] 21. The DeepSeek summarization pass.
- [ ] 22. The `summarize` stage, runner, and force flag.
- [ ] 23. Cost reporting.
- [ ] 24. Documentation and configuration.
- [ ] 25. End-to-end fixture run.
- [ ] 26. Review, verify, live proof, report.

## Task ledger — `O2` (stale position; implementation merged)

- [x] 1. Seed the `title_inclusion` keyword rules.
- [x] 2. Add the `filtered` processing status and its migration.
- [x] 3. Write the keyword gate function.
- [x] 4. Add the repository seams and fix the stub status filter.
- [x] 5. Store discoveries without fetching the page.
- [x] 6. Write the gate-and-fetch retrieval pass.
- [x] 7. Add the `retrieve` stage and its runner.
- [x] 8. Add the `pregroup` stage and enable it by default.
- [x] 9. Select for extraction without the relevance pass.
- [x] 10. Move the extraction schema to version 3.
- [x] 11. Validate every span against the member it cites.
- [x] 12. Build the cluster prompt.
- [x] 13. Read a story group as one extractable cluster.
- [x] 14. Run cluster extraction with a per-article fallback.
- [x] 15. Wire cluster extraction into the extract stage.
- [x] 16. Report what clustering bought in `spend:report`.
- [x] 17. Update `CONTEXT.md` and write the ADR.
- [ ] 18. Capture live proof against the recorded baseline.
- [ ] 19. Review, verify, report, and hand back.

## Task ledger — `M` (complete)

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
- [x] 13. Build the accessible cause-specific review queue.
- [x] 14. Mount the inspired review workspace in the existing web shell.
- [x] 15. Review, verify, capture safe live proof, and report.

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

## Queued behind `O2` — item `R`

`R` — Event-based surveillance is **planned**, not active. `HANDOFF.md` stays
with `O2` until that item is verified.

[Spec](docs/superpowers/specs/2026-08-29-event-surveillance-pipeline-design.md) ·
[plan](docs/superpowers/plans/2026-08-29-event-surveillance-pipeline.md) — 26
tasks in three separately verified phases: structured Llama triage after the
keyword gate, pgvector + BGE-M3 embeddings consulted only for pairs the
deterministic guards already permit, and DeepSeek event summaries with a
versioned history. The worker branches from `codex/pipeline-funnel-v2` once
`O2` is verified; the plan is written against the post-`O2` code shape.

Seven conflicts between the operator's brief and this codebase are resolved in
the spec's **Conflicts with the brief** table. The load-bearing one: embedding
similarity may add confidence to a match but may never veto one, because a
false merge hides a geographically distinct outbreak.

## Blockers

**None.** `M` is `verified`. `O2` is planned and unblocked; its branch base is
the head of `codex/manual-review-queue`, which carries `M`'s unmerged work.

## Verified baseline

Everything below was true at commit `5163130` on branch `codex/manual-review-queue`. Recorded from the
`M` run logged in
[docs/reports/2026-08-29-subproject-m-report.md](docs/reports/2026-08-29-subproject-m-report.md).

| Fact | Value |
| --- | --- |
| Verification command | `corepack pnpm verify` — exit code 0 |
| Python tests | 949 passed, 2 warnings |
| Web tests | 75 passed, 10 files |
| Lint and format | `ruff check` and `eslint` clean, 226 files formatted |
| Types | `tsc` and `mypy` clean across 113 source files |
| Migration revision | `20260829_0014_manual_review_cases` |
| Live database | `db:migrate` and `db:seed` applied: 64 open review cases reconciled (34 retrieval_failed, 28 disease_unresolved, 1 legacy_unclassified, 1 content_integrity) |
| Canonical diseases | 29 stable of 29 rows |
| Canonical sources | 2 stable and inactive |
| Extraction schema | `extraction_schema_version: 2`, 5-slot brief, English title, provider-routed structured outputs |
| Model ladder | `google/gemini-3.1-flash-lite` (T1), `google/gemini-3.5-flash-lite` (T2), `mistralai/mistral-small-24b-instruct-2501` (T3 fallback); reordered at `02c23a7` per operator instruction |
| Trailing AI spend | `spend:report` — 30 days, 139 requests, $0.118554 |
| Pre-group stage | Built, `pregroup_enabled=false`; measurement gate decided no flip |
| Radar & Admin endpoints | `GET /api/v1/radar`, `GET /api/v1/admin/pipeline-runs`, `GET /api/v1/admin/reviews`, `POST /api/v1/admin/reviews/{case_id}/resolve` |
| Production Web Routes | `/`, `/admin/pipeline`, `/admin/reviews` |

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
