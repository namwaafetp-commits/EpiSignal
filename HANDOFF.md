# Handoff — Sub-Project O2: Pipeline Funnel v2

**Date:** 2026-08-29
**Item:** `O2` — Pipeline funnel v2 (keyword gate, deferred retrieval, cluster extraction)
**Branch:** create `codex/pipeline-funnel-v2` in a separate worktree from the
head of `codex/manual-review-queue`. That branch carries today's unmerged
prerequisite work — the review queue, story grouping, the disease classifier,
and the extraction performance changes. Branching from `main` would build on a
tree that does not have them.
**State:** `O2` is **planned**. The corrected spec and the 19-task plan are
committed.
**Role:** implementation worker.

---

## Outcome

Re-shape the ingestion funnel so attention is spent in the order evidence
deserves it. A seeded keyword gate decides relevance from the title before any
model call or body download; only passing articles are retrieved; the built but
disabled pre-group stage is turned on to form story groups; and extraction runs
once per story group over all its members, grounded per member, instead of once
per article. Geocoding, event matching, the review queue, and the radar read
model do not change.

```
discover (title + url only)
  -> keyword gate -> retrieve body           [new stage: retrieve]
  -> dedupe
  -> pre-group                               [new stage: pregroup]
  -> cluster extraction, one call per story  [stage: extract]
  -> geocode -> match
```

The approved and corrected design is
[docs/superpowers/specs/2026-08-29-pipeline-funnel-v2-design.md](docs/superpowers/specs/2026-08-29-pipeline-funnel-v2-design.md).
The executable plan is
[docs/superpowers/plans/2026-08-29-pipeline-funnel-v2.md](docs/superpowers/plans/2026-08-29-pipeline-funnel-v2.md).

## Start here

1. Read `AGENTS.md`, `STATUS.md`, `CONTEXT.md`, and `docs/agents/workflow.md`.
2. Read the design and the plan in full, including the plan's **Corrections**
   table — it records eight places where the approved design disagreed with the
   code, and the plan implements the corrected version. Do not re-derive them.
3. Create the worktree:

```bash
git worktree add ../EpiSignal-funnel-v2 -b codex/pipeline-funnel-v2 codex/manual-review-queue
```

4. Copy `apps/api/.env` into the new worktree — it is not committed and nothing
   runs without it.
5. Run a clean baseline (`corepack pnpm install && corepack pnpm verify`) before
   Task 1. If it is red, stop and report; do not start on a red tree.
6. Load the project-local `lean-build`, `tdd`, and `migration` skills.
7. Start Task 1 test-first. Set `O2` to `building` in `ROADMAP.md` in the Task 1
   commit, and tick each ledger item in `STATUS.md` only in the commit that
   completes it.

## Load-bearing decisions

- **The gate reuses `filter_rules`.** `FilterRuleGroup` gains
  `title_inclusion`; there is no new table. Seeded rows carry context and
  pathogen terms only — disease names are read from the `diseases` table, so the
  reviewed vocabulary stays the single source of disease identity.
- **The gate is biased to pass.** No active rules means every title passes. A
  filtered measles story costs more than an extra extraction.
- **`filtered` is a terminal status that preserves the row.** Nothing is ever
  deleted. A filtered row is re-gated by setting it back to `fetched`.
- **`processing_status` is a CHECK constraint, not a pg enum.** The migration
  drops and recreates `processing_status_values`, exactly as
  `20260829_0014` did for `dismissed`. `ALTER TYPE` will fail.
- **Retrieval must complete before the dedupe stage.** Dedupe compares bodies
  and is the only writer of `normalized`; a bodyless signal is invisible to it
  forever. This is why `retrieve` is a stage and not a prefix inside `extract`.
- **`stubs_awaiting_retrieval` needs a `needs_review` status filter.** Today it
  selects any GDELT signal with a null body. Left alone, the discover stage's
  retry pass would fetch every gate-passed signal before the gate ran, and would
  re-fetch every filtered signal forever.
- **The deferral exclusion moves to `awaiting_extraction`.** It currently
  applies only to `awaiting_classification`. Once the relevance pass leaves the
  chain, extraction is the selection that has to honour it, or every deferred
  member is extracted individually and the whole saving disappears.
- **Every claim in a cluster extraction cites `source_index`, and the validator
  checks the span against that member's text only.** Provenance survives
  batching or the design is wrong. Per-article extraction becomes the one-member
  case, so one grounding implementation serves both paths and they cannot drift.
- **A rejected cluster call falls back to per-article extraction** for that
  group's members. One bad article must not poison the group's retry budget.
- **The accepted cluster extraction is stored on the representative signal;**
  members become `duplicate` pointing at it. Downstream stages see one signal
  per story with zero read-model changes.
- **The backfill floor stays at 2 while the version moves to 3.** Tying
  `awaiting_backfill` to the version constant would make every stored v2 row a
  backfill candidate and re-extract the corpus on the next run.
- **Grouping is deterministic routing** (rule group + country + window), never
  model judgement.

## Rollback levers

No new configuration flag is introduced. `pregroup_enabled=false` writes no
groups, so cluster extraction selects nothing and every signal takes the
per-article path that exists today. The relevance pass is unwired from the
chain but `ai/classify.py` is kept intact, so restoring it is one line in
`schedule/stages.py`. Deferred retrieval has no flag; its rollback is a revert.

## Baseline to beat

Recorded 2026-08-29 on the live database: **105 extraction requests for 43
extracted signals**, 35 unclusterable review cases, **~$0.30 lifetime ledger**
at that point. The report must compare against these numbers.

Two more numbers the report must carry: the count of rows selectable by
`awaiting_backfill` before and after the schema version moves (they must
match), and the share of examined signals the gate filtered.

## Scope guard

Do not build embeddings, `D2b`, Gemini batch wiring, radar cluster display, new
review flows, or a new configuration flag. Do not delete `ai/classify.py`. Do
not resolve live review cases for demonstration. Synthetic fixtures stay
clearly labelled, disposable, and are never presented as live proof.

## Completion

Task 19 loads `code-review`, then `verify-and-stop`, runs the real
`corepack pnpm verify`, captures the live comparison from Task 18, writes
`docs/reports/2026-08-29-pipeline-funnel-v2-report.md`, and updates the
worker-owned **Verified baseline** in `STATUS.md` with the commit it actually
ran at. Then hand back to the planner.

Do not mark `O2` `verified` and do not begin another roadmap item.

**If the plan turns out to be wrong, stop and report.** Correcting a plan is
planner work. Improvising a different design is the one failure this contract
does not tolerate.
