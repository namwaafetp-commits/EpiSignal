# Handoff — Sub-Project M: Manual Review Queue

**Date:** 2026-08-29
**Branch:** create `codex/manual-review-queue` in a separate worktree
**State:** `M` is **planned**. The design and 15-task implementation plan are committed.
**Role:** Implementation worker.

---

## Outcome

Build the authenticated internal escape hatch for signals where automation
refuses to continue. Every transition to `needs_review` must open a durable,
typed review case. The operator sees safe decision evidence and may retry the
responsible stage, assign a canonical disease, link or create an event through
the existing event-finalization rules, or dismiss the signal without deleting
evidence. Every resolution records who decided, when, why, and any selected
disease or event. Radar, pipeline, and review surfaces also adopt the supplied
dark, map-dominant surveillance-console language without changing evidence
semantics.

The approved design is
`docs/superpowers/specs/2026-08-29-manual-review-queue-design.md`. The executable
plan is `docs/superpowers/plans/2026-08-29-manual-review-queue.md`.

## Start here

1. Read `AGENTS.md`, `STATUS.md`, `CONTEXT.md`, and
   `docs/agents/workflow.md`.
2. Read the approved design and implementation plan in full.
3. Load `superpowers:using-git-worktrees`, create
   `codex/manual-review-queue` from current `main`, and work only in that
   worktree. Never check out a feature branch in the primary tree.
4. Load `superpowers:executing-plans` or
   `superpowers:subagent-driven-development`, then project-local `lean-build`,
   `tdd`, and `migration`.
5. Before editing Next.js files, read `apps/web/AGENTS.md` and the applicable
   installed guides under `apps/web/node_modules/next/dist/docs/`.
6. Start Task 1 test-first. Set `M` to `building` in `ROADMAP.md` in that first
   task commit. Tick the matching `STATUS.md` task in every task commit.

## Why this item is next

`E` is verified, so `M` is dependency-ready. A live read on 2026-08-29 found
37 signals at `needs_review`: 28 accepted extractions whose disease did not map
to a canonical disease, 7 rows with no retrieved text, 1 quarantined content
integrity mismatch, and 1 deterministic event-match refusal. The causes are
inferred from state because the current schema does not store a review reason;
`M` fixes that provenance gap.

Only 3 events existed in the last recorded live proof. `G` would expose a
nearly empty table. `D2b` could improve the one ambiguous match, and `F` could
improve future model choice, but neither resolves the other 36 stopped signals.

## Load-bearing decisions

- A review case is durable history, not a computed view over
  `processing_status`. Only one case may be open for a signal; closed cases are
  never erased.
- Reasons are closed vocabulary: retrieval failure, extraction rejection,
  unresolved disease, ambiguous event match, content integrity, or conservative
  legacy fallback.
- `dismissed` is a new terminal processing status. Dismissal preserves the
  signal and does not claim its source was wrong.
- Event refusals snapshot candidate event IDs and deterministic match scores.
  Manual linking accepts only a stored candidate.
- Manual link/create and automated assembly share one extracted event
  finalization module so observations, locations, dual scores, verification
  status, and provenance cannot drift.
- Retry never performs model or publisher network work inside the HTTP request.
  It returns the signal to the earliest safe state for the existing scheduled
  stage.
- All review endpoints require `EPISIGNAL_ADMIN_TOKEN`. The browser keeps the
  operator-entered token only in component memory and sends it only in the
  `Authorization` header.
- Queue reads never expose raw text, source spans, prompts, credentials,
  exception messages, or patient-level data.
- The supplied UI image is visual direction only: dark navy structure, cyan
  selection, dense work-area-plus-rail layouts, Geist/Geist Mono, and Phosphor
  icons. Do not copy its invented severity, counts, locations, publishers, or
  reviewed-state claims, and never collapse EpiSignal's two scores.
- The migration expands, backfills conservatively, verifies exact case/signal
  reconciliation, and refuses destructive downgrade after live review history
  exists.

## Live baseline to preserve

The planner's read-only classification at planning time was:

```text
needs_review total                    37
disease_unresolved                   28
retrieval_failed                      7
content_integrity                     1
event_match_ambiguous                 1
```

These counts are evidence for planning, not hard-coded migration expectations.
Re-query immediately before migration because the scheduler may change them.
Preserve the quarantined signal
`852aa204-846d-4aa6-a256-82c187fdeaef`; do not repair or dismiss it for proof.

## Scope guard

Do not build accounts, roles, sessions, assignments, comments, notifications,
batch actions, arbitrary event search, raw-text or extraction editing, location
editing, event observation editing, automatic corruption repair, `D2b`, `G`,
`H`, or `I`. Do not delete signals, cases, AI cost rows, events, observations,
or source evidence.

Do not resolve live reporting solely to demonstrate a button. Live acceptance
uses only a clearly synthetic disposable fixture. If none exists, record the
blocker, leave `M` at `building`, and hand back without claiming completion;
automated tests do not replace this acceptance condition.

## Completion

Task 15 loads `code-review`, then `verify-and-stop`, runs the real
`corepack pnpm verify` gate, captures safe live queue and database proof, and
writes `docs/reports/2026-08-29-subproject-m-report.md`. Record exact output and
update the worker-owned verified baseline. Commit the report and hand back to
the planner. Do not mark `M` verified and do not begin another roadmap item.

## Incoming baseline

The planner independently ran `corepack pnpm verify` at `2499e4e` on `main`:
848 Python tests passed with 1 warning, 58 web tests passed across 8 files, Ruff
and ESLint were clean, mypy and tsc were clean across 97 source files, generated
contracts matched, and the Next production build succeeded. Documentation-only
planner commits then reconciled `E`, designed `M`, and committed this plan; run
the worker's own baseline in the new worktree before Task 1.
