# Planner and Worker Workflow

Two roles build this repository. This document says what each one does, which
files each one writes, and what must be true before an item is called done. It is
the contract that lets a planner and a worker resume independently without
disagreeing about where the build stands.

Roles are jobs, not people and not models. One agent may hold both roles in one
session, but it must not hold both at the same moment: finish planning, then
start building.

## The three tracking files

| File | Holds | Changes | Written by |
| --- | --- | --- | --- |
| `ROADMAP.md` | The whole road, banded, with per-item status | On scope change | Planner |
| `STATUS.md` | The current position and the active task ledger | Constantly | Planner sets position, worker ticks tasks |
| `HANDOFF.md` | The deep briefing for the active item | On retarget | Planner |

`ROADMAP.md` and `STATUS.md` are separate on purpose. Stable content and volatile
content in one file means two roles editing the same lines and a diff nobody can
read.

## Roles

### Planner

Uses the judgment tier described in `AGENTS.md`.

Owns: `ROADMAP.md`, `HANDOFF.md`, design specs under
`docs/superpowers/specs/`, implementation plans under `docs/superpowers/plans/`,
and the **Position**, **Next action**, and **Blockers** sections of `STATUS.md`.

Does:

1. Reads `STATUS.md` first. It is the only file that must be read to learn the
   position.
2. Picks the next item from `ROADMAP.md`, honouring the depends-on column.
3. Brainstorms the item into a design spec, and commits it.
4. Turns the spec into a numbered implementation plan, and commits it.
5. Archives the outgoing `HANDOFF.md` to
   `docs/handoffs/YYYY-MM-DD-<id>.md`, then rewrites `HANDOFF.md` for the new
   item.
6. Copies the plan's numbered tasks into the `STATUS.md` task ledger as unticked
   checkboxes and updates **Position** and **Next action**.
7. After the worker passes the gate, sets the item to `verified` in
   `ROADMAP.md` and advances the position.

Only the planner adds, removes, or reorders roadmap items, and only the planner
changes an item's dependencies. A worker that believes the roadmap is wrong says
so; it does not edit it.

### Worker

Uses the balanced or fast tier described in `AGENTS.md`, escalating as that
document requires.

Owns: source code, tests, migrations, seeds, and the completion report. In
`STATUS.md` it owns the **Task ledger** ticks and the **Verified baseline**,
because it is the role that actually ran the commands.

Does:

1. Reads `HANDOFF.md` and the committed plan. Reads `STATUS.md` to find the
   first unticked task.
2. Sets the item to `building` in `ROADMAP.md` when it starts the first task.
   This is the one roadmap edit a worker makes.
3. Executes tasks in order, test-first, per the `tdd` and `lean-build` project
   skills.
4. Ticks each task in `STATUS.md` as it lands, in the same commit as the work.
5. Runs the full verification command and records its real output, updating the
   **Verified baseline** in `STATUS.md` with the commit it ran at.
6. Writes the completion report to `docs/reports/YYYY-MM-DD-<id>-report.md` and
   commits it.
7. Hands back to the planner. It does not mark the item `verified` itself.

A worker that finds the plan wrong stops and reports rather than improvising a
different design. Correcting a plan is planner work.

## Status state machine

```text
not-started ──> designing ──> designed ──> planned ──> building ──> verified
                                                          │
     any state ────────────> blocked ──────────> back to the state it left
```

| Status | Set by | Set when |
| --- | --- | --- |
| `not-started` | Planner | The row is created. |
| `designing` | Planner | Brainstorming begins. |
| `designed` | Planner | The spec is committed. |
| `planned` | Planner | The plan is committed. |
| `building` | Worker | The first task begins. |
| `verified` | Planner | The gate below has been passed. |
| `blocked` | Either | Progress needs a decision or an upstream item. Record what it waits on in `STATUS.md`. |

Do not invent status words. The set is closed, and both `ROADMAP.md` and
`STATUS.md` use it identically.

## The completion gate

An item becomes `verified` only when all of the following are true:

1. Every task in its plan is ticked.
2. `corepack pnpm verify` ran and reported zero failures.
3. The real output of that run is quoted in the item's completion report — the
   test counts, not a claim that tests passed.
4. The report is committed and linked from the item's row in `ROADMAP.md`.
5. `STATUS.md`'s verified baseline is updated to the commit the run was
   performed at.

This is the `verify-and-stop` project skill applied to roadmap items. It is not
waived for small items, and it is not waived for documentation-only items.

Never claim a gate passed without having run the command in that session. If the
run did not happen, the item stays `building`.

## Retargeting

When an item reaches `verified` and the next one begins:

```powershell
# 1. archive the outgoing briefing, do not overwrite it
Copy-Item HANDOFF.md docs/handoffs/2026-08-27-d1.md

# 2. planner rewrites HANDOFF.md for the new item
# 3. planner updates ROADMAP.md status and STATUS.md position
# 4. commit the three together so the tree is never half-retargeted
```

Archive first. The briefing explains why an item was built the way it was, and
that reasoning is worth more after the item ships than before.

## Relationship to the issue tracker

`docs/agents/issue-tracker.md` is unchanged. GitHub Issues remain the surface for
discrete tickets, triage, and questions. The roadmap is the map of the build. If
a `wayfinder:map` issue is used, it mirrors `ROADMAP.md`; the file in the
repository is the source of truth, because it is readable without a network and
it is versioned with the code it describes.

## When the two disagree

If `STATUS.md` and the code disagree, the code is right and `STATUS.md` is stale.
Fix the file, record the commit you checked at, and say so in the next report.
Do not silently work around a wrong status file — a tracking file nobody trusts
is worse than no tracking file.
