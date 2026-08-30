# Master Tracking and Long Roadmap — Design

**Date:** 2026-08-28
**Status:** Approved
**Depends on:** `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md`, `AGENTS.md`

## Problem

Two agents work this repository: a planner that designs and plans, and a worker
that implements. Neither can answer "where are we now" from a single place.

The information exists, but it is scattered and partly perishable:

- `HANDOFF.md` targets exactly one sub-project and is overwritten each time the
  target moves, so the briefing history is destroyed on every retarget.
- Completion reports live in three different shapes and locations: `reportback.md`
  for sub-project A, `report.md` for B, and `docs/reports/` for C and D1.
- The road ahead lives in two documents that were never reconciled. The layer
  architecture holds the A–F table for the GDELT layer only. The Phase 1 build
  specification holds sixty-three sections, a twelve-step build sequence, and the
  MVP acceptance criteria. Neither carries status.
- Work completed before the GDELT layer, including the foundation, WHO DON and
  ECDC ingestion, and the signal evidence browser, appears in no roadmap at all.

Resuming work therefore costs a full re-read of several completion reports, and
the planner and the worker can disagree about what is done without either of
them being wrong.

## Goal

One durable, committed answer to three questions, readable by either agent with
plain file tools and no network:

1. What is the whole remaining road to the Phase 1 MVP?
2. Where are we on it right now?
3. Who writes what next, and what gate must be passed before an item is done?

## Non-goals

- Replacing GitHub Issues. `docs/agents/issue-tracker.md` stands unchanged. The
  roadmap is the map of the build; issues remain the surface for discrete
  tickets and triage.
- Enumerating tasks for items that have no committed plan yet. Future task lists
  are guesses and rot.
- Restating the Phase 1 specification. The roadmap points at it; it does not
  duplicate it.

## Architecture

Four files, each with one job and one owner. The split is deliberate: stable
content and volatile content are separated so that the planner and the worker are
not editing the same lines, and so a status change produces a small readable
diff.

### `ROADMAP.md` (repository root)

The long road. Stable; it changes only when scope changes.

Items are grouped into six bands. Each row carries an identifier, what the item
is, the condition that ends it, what it depends on, its status, and links to its
spec, plan, and report.

| Band | Contents |
| --- | --- |
| 0 Foundation | `P0` |
| 1 Official source ingestion | `P1`, `P2`, `P3` |
| 2 GDELT discovery layer | `A`, `B`, `C`, `D1`, `D2`, `F` |
| 3 Product surface | `E`, `G`, `H`, `I`, `J`, `K` |
| 4 Operations | `L`, `M`, `N` |
| 5 Acceptance | `Z` |

Identifiers `A` through `F` keep the meanings the layer architecture already
assigned them, so no existing document needs editing. `P0` through `P3` are
retrofitted onto the work that predates the GDELT layer. `G` onward continues the
letter sequence for work the layer architecture never covered.

Phase 2 and Phase 3 appear as a short horizon note rather than as rows, because
they are direction rather than committed scope.

### `STATUS.md` (repository root)

Where we are now. Volatile, small, and fixed in shape so that a diff shows the
change and nothing else. Its sections are:

- **Position** — band, item identifier, and status.
- **Next action** — one sentence naming the exact next task number or, when no
  plan exists yet, the next planning step.
- **Task ledger** — the numbered checklist copied from the committed plan of the
  active item. Empty while the active item has no plan.
- **Blockers** — open decisions and upstream waits, or an explicit "none".
- **Verified baseline** — test counts, migration revision, seed counts, and the
  commit that last verified green.

### `HANDOFF.md` (repository root)

Keeps its present role as the planner's deep briefing for the active item:
reading order, environment facts, inherited constraints, carried-forward
follow-ups, and invariants. One change: before retargeting, the outgoing briefing
is copied to `docs/handoffs/YYYY-MM-DD-<id>.md` rather than overwritten, so the
reasoning behind each completed item survives.

### `docs/agents/workflow.md`

The planner and worker contract: roles, the status state machine, which agent
writes which file at which moment, and the completion gate. It sits beside
`issue-tracker.md`, `triage-labels.md`, and `domain.md`, and is referenced from
`AGENTS.md` in the same way those are.

## Status vocabulary

One closed set, used with identical meaning in `ROADMAP.md` and `STATUS.md`:

| Status | Meaning |
| --- | --- |
| `not-started` | No design work has begun. |
| `designing` | Brainstorming is under way; no spec is committed. |
| `designed` | A spec is committed under `docs/superpowers/specs/`. |
| `planned` | An implementation plan is committed under `docs/superpowers/plans/`. |
| `building` | Tasks are being executed; some are ticked. |
| `verified` | Every task is done, the full verification command is green, and a report is committed. |
| `blocked` | Progress needs a decision or an upstream item. |

The order runs `not-started`, `designing`, `designed`, `planned`, `building`,
`verified`. `blocked` may be entered from any state and records what it is
waiting on.

## Ownership

Ownership is the mechanism that keeps the two agents in agreement. Each file has
exactly one writer per phase.

**Planner writes** `ROADMAP.md`, `HANDOFF.md`, specs, and plans. It advances an
item's status as far as `planned`. Only the planner may add, remove, or reorder
roadmap items, and only the planner may change an item's dependencies.

**Worker writes** code, tests, the completion report, and in `STATUS.md` the task
ticks and the verified baseline, because it is the role that ran the commands.
It sets the item to `building` when it starts and asks the planner to record
`verified` once the gate is passed. Only the worker may tick a task.

**Neither** marks an item `verified` without the output of `corepack pnpm verify`
recorded in that item's report. This is the gate the `verify-and-stop` project
skill already requires; the roadmap does not invent a second one.

**Resuming.** The planner reads `STATUS.md` to learn the position, then the
active item's spec or report. The worker reads `HANDOFF.md` and the committed
plan. Neither has to read three completion reports to find out what is done.

## Data flow through one item

```text
planner: add row to ROADMAP.md            status not-started
planner: brainstorm                       status designing
planner: commit spec                      status designed
planner: commit plan                      status planned
planner: write HANDOFF.md, archive old    STATUS.md position updated
worker:  begin task 1                     status building
worker:  tick tasks in STATUS.md          ledger advances
worker:  corepack pnpm verify green
worker:  commit report                    gate passed
planner: mark verified, advance position  status verified
```

## Testing

These are documentation artifacts and carry no executable behaviour, so they add
no test suite. Their correctness condition is consistency, which is checked by
reading:

- every roadmap row's artifact links resolve to files that exist;
- every status word in both files comes from the closed set above;
- `STATUS.md`'s verified baseline matches the most recent completion report;
- the roadmap's `A` to `F` rows agree with the layer architecture table.

The existing `corepack pnpm verify` gate is unaffected and must remain green.

## Risks

**Drift.** A status file is only useful while it is true. The ownership rules and
the single completion gate are the mitigation: status changes are a required step
of the same commit sequence that already produces specs, plans, and reports, not
an optional bookkeeping chore afterwards.

**Duplication.** The roadmap could grow into a restatement of the Phase 1
specification. The ends-when column is the mitigation: each row states its
completion condition in one sentence and links out for the detail.
