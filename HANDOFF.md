# Handoff — Pipeline Funnel v2

**Date:** 2026-08-29
**Branch:** create `codex/pipeline-funnel-v2` in a separate worktree from the
head of `codex/manual-review-queue` (unmerged prerequisite work lives there).
**State:** `pipeline-funnel-v2` is **planned**. Spec and 14-task plan are
committed.
**Role:** implementation worker.

---

## Outcome

Re-shape the ingestion funnel so attention is spent in the order evidence
deserves it: a seeded keyword gate decides relevance from the title before any
model call or body download; only passing articles are retrieved; the built
but disabled pre-group stage is turned on to form story groups; and extraction
runs once per story group over all its members, grounded per member, instead
of once per article. Geocoding, event matching, the review queue, and the
radar read model do not change.

The approved design is
`docs/superpowers/specs/2026-08-29-pipeline-funnel-v2-design.md`. The
executable plan is
`docs/superpowers/plans/2026-08-29-pipeline-funnel-v2.md`.

## Start here

1. Read `AGENTS.md`, `STATUS.md`, `CONTEXT.md`, and
   `docs/agents/workflow.md`.
2. Read the approved design and implementation plan in full.
3. Create the worktree branch and run a clean baseline
   (`corepack pnpm verify`) before task 1.
4. Load the project-local `lean-build`, `tdd`, and `migration` skills.
5. Start task 1 test-first. Tick each task in the commit that completes it.

## Load-bearing decisions

- The gate is seeded data, loose by default, and biased to pass: a filtered
  measles story costs more than an extra extraction.
- `filtered` is a terminal status that preserves the row and the matched rule;
  nothing is ever deleted.
- Retrieval failure after a gate pass uses the existing `retrieval_failed`
  review path; no new failure semantics.
- Grouping is deterministic routing (rule group + country + window), never
  model judgement.
- Every claim in a cluster extraction cites `source_index`, and the validator
  checks the span against **that member's text only**. Provenance survives
  batching or the design is wrong.
- A rejected cluster call falls back to per-article extraction for that
  group's members; one bad article must not poison the group's retry budget.
- The accepted cluster extraction is stored on the representative signal;
  members become `duplicate` pointing at it. Downstream stages see one signal
  per story with zero read-model changes.

## Baseline to beat

Recorded 2026-08-29 on the live database: 105 extraction requests for 43
extracted signals, 35 unclusterable review cases, ~$0.30 lifetime ledger at
that point. The report must compare against these numbers.

## Scope guard

Do not build embeddings, D2b, Gemini batch wiring, radar cluster display, new
review flows, or anything listed in the plan's scope guard. Do not resolve
live review cases for demonstration. Synthetic fixtures follow the synthetic
rule: clearly labelled, disposable, never claiming to be live proof.

## Completion

Task 14 loads `code-review`, then `verify-and-stop`, runs the real
`corepack pnpm verify`, captures the live comparison run, writes
`docs/reports/2026-08-29-pipeline-funnel-v2-report.md`, updates the
worker-owned verified baseline in `STATUS.md`, and hands back to the planner.
Do not mark the item verified and do not begin another roadmap item.
