# Handoff — Sub-Project L: Scheduler

**Date:** 2026-08-28
**Branch:** `main` (clean, 694 passing tests)
**Head:** `D2a` complete and verified; `events`, `event_signals`, `event_observations`, and `event_locations` have a working writer, and every stage of the pipeline exists as a CLI runner.
**State:** `P0`–`P3`, `A`, `B`, `C`, `D1`, and `D2a` are complete, verified, and merged. `L` is **designed and planned**. **Your task is to implement Sub-Project L, task by task, from the committed plan.**

---

## Why this item, and why now

Every stage of the pipeline works. Nothing runs it.

`D2a`'s live verification is the whole argument for this item:

```
seen=2 clusters=0 created=0 attached=0 refused=0 unclusterable=2
```

Two geocoded signals, zero events. Not because clustering is wrong — because
seven commands have to be typed in order, by hand, and nobody has been typing
them. `D2b` would tune an embedding threshold against zero refusals, and `E`
would render an empty list. Both are worth building once there is a corpus. This
item is what produces one.

---

## What Sub-Project L Builds

1. **One command that runs the whole chain.** `pnpm pipeline:run` executes
   `ingest_who → ingest_ecdc → discover → dedupe → extract → geocode → match`
   once, then exits. No daemon, no queue, no in-process scheduler.
2. **A run record.** A new `pipeline_runs` table holds one row per run: what
   each stage did, how deep the backlog is, and the window discovery asked for.
3. **A recoverable missed day.** Discovery's window starts where the last
   successful run stopped, clamped to seven days, so a laptop that was asleep
   costs a longer run rather than a permanent hole.
4. **A lock.** A PostgreSQL advisory lock, so a manual run and a scheduled one
   cannot collide.
5. **A trigger.** `scripts/run-pipeline.ps1` plus a documented Windows Task
   Scheduler entry.

---

## Scope note: this is an orchestrator

`L` writes no signal, no event, and no observation of its own. Every stage it
calls is an existing, already-verified path, and each is idempotent by
`processing_status`. `L` adds three things those paths do not have: an order, a
record, and a lock.

If you find yourself changing what a stage *does* — editing `run_geocoding`,
`run_extraction`, `run_event_assembly`, or any repository under `events/`,
`geocode/`, `ai/`, or `ingestion/` — you have left this item. Stop and report.
The one exception is `schema_check.py`, which task 9 changes by design.

---

## Start Here

Read in this exact order:

1. This file (`HANDOFF.md`);
2. `STATUS.md` — the current position, the 18-task ledger, settled decisions, and the verified baseline;
3. `ROADMAP.md` — where `L` sits;
4. `docs/agents/workflow.md` — the planner and worker contract and the completion gate;
5. `docs/superpowers/specs/2026-08-28-scheduler-design.md` — the design you are implementing;
6. `docs/superpowers/plans/2026-08-28-scheduler.md` — the 18 tasks, in order;
7. `AGENTS.md` — model routing, project skills, TDD rules, token efficiency, provenance principles;
8. `CONTEXT.md` — the naming authority. Note the spec's **Vocabulary** section: *stage* means a step of the pipeline here and never a rung of the model ladder, which is a *tier*;
9. `docs/reports/2026-08-28-subproject-d2a-report.md` — the outgoing item's completion report;
10. `docs/handoffs/2026-08-28-d2a.md` — the briefing `D2a` was built under.

When `L` reaches `verified`, archive this file to `docs/handoffs/2026-08-28-l.md`
before rewriting it for the next item. Do not overwrite it in place.

---

## Windows Environment Facts

- **Python:** Run all commands through `uv run`. Do not activate virtual environments manually. Bare `python` is not on `PATH`; use `uv run python`.
- **Node / pnpm:** `pnpm` is not on `PATH`, but `corepack` ships with Node and is. Always enter the workspace through `corepack pnpm <command>` (for example `corepack pnpm verify`, `corepack pnpm db:migrate`, `corepack pnpm pipeline:run`).
- **PowerShell:** Commands run under Windows PowerShell 5.1 (no `&&`, no ternary, no `??`). Chain with `;`.
- **UTF-8 BOM:** Strip UTF-8 BOM from generated scripts or use standard python writers.
- **This is a shared working tree.** Other agents commit to `main` in this same directory. Commit only the files your task names; never `git add -A`.

---

## Verified Baseline

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src packages/backend/src
corepack pnpm verify
```

**Expected baseline output at `6d61554`:**
- `694 passed, 1 warning`
- `All checks passed!`
- `158 files already formatted`
- `Success: no issues found in 82 source files`
- Web: `10 passed (10)`, 3 test files
- `corepack pnpm verify` runs format, lint, typecheck, both test suites, contracts check, and Next.js build cleanly.

The database is at migration revision `20260828_0007_event_scores`.

---

## Testing Rules That Are Not Optional

- **No test touches a database, a socket, or a model.** There is no
  `conftest.py` and no fixture database in this repository. Repository tests use
  a hand-written `FakeSession` — copy the one at the top of
  `packages/backend/tests/test_event_repository.py`.
- **Only task 18 touches the live database.** Tasks 1 through 17 need no key, no
  network, and no database.
- **Test-first, red then green.** The plan gives you the failing test, the
  command to prove it fails, and the expected failure message for every task.
- Tests are flat files in `packages/backend/tests/`, named
  `test_schedule_<module>.py`.

---

## Invariants for Sub-Project L

1. **Pure modules import no driver.** `documents.py`, `chains.py`, `window.py`,
   `protocol.py`, and `run.py` import neither `sqlalchemy`, `geoalchemy2`, nor
   `httpx`. `repository.py` is the only module in `schedule/` that imports
   SQLAlchemy. Task 16 enforces this; obey it from task 1.
2. **A failing stage never stops the chain.** Every stage selects its own
   backlog by `processing_status`, so a failed extraction does not invalidate
   work already waiting to be geocoded. Run every stage, record which failed,
   exit non-zero.
3. **Failures are recorded by exception type, never by message.** An exception
   raised near the session can carry the connection string; one raised near a
   prompt can carry the article. `type(error).__name__` and nothing else.
4. **The run row is written before the first stage.** A run killed mid-flight
   must leave a `running` row with a null `finished_at`. Nothing cleans those
   up — that row is the evidence.
5. **The advisory lock is session-level, not transaction-level.** It must
   survive a stage's rollback and die with the process.
6. **Losing a run is acceptable; losing it silently is not.** When the catch-up
   window is clamped, the run still records the window it actually asked for.
7. **Do not call a runner's `main()` or `_run()` from a stage.** Those parse
   argv, print, and return exit codes. Call the same domain function the runner
   calls.

---

## Settled Decisions — Do Not Reopen

These were decided in the design and approved. Implement them; do not relitigate
them in code.

- **The OS drives the cadence.** One-shot CLI plus Windows Task Scheduler. No
  APScheduler, no Celery, no daemon, no queue. Phase 1 §42.
- **One chain, `daily`, in the order the spec gives.** WHO and ECDC first, so an
  official document that corroborates a story is in the database before that
  story's media coverage is matched.
- **Continue past a failing stage.** Not abort-on-first-failure.
- **A `pipeline_runs` table, not stdout alone.** Journald does not exist on
  Windows and item `E` needs a table to render.
- **The cadence settings are `.env`, not code defaults.** The existing
  `window_covers_the_interval` validator already enforces the relationship. Do
  not change `gdelt_poll_interval_minutes`' default in `config.py`.

---

## Known Trap: the budgets do not compose

Discovery stores up to `EPISIGNAL_GDELT_MAX_ARTICLES_PER_RUN` (default `200`)
per run. Extraction handles up to `EPISIGNAL_AI_SIGNAL_BATCH_LIMIT` (default
`100`). Run daily at those defaults and the un-extracted backlog grows by one
hundred signals a day, for ever.

Do **not** fix this by changing code defaults for a traffic pattern nobody has
measured. Task 10's `backlog_depth` records the count at each
`processing_status` on every run, and task 15 recommends
`EPISIGNAL_GDELT_MAX_ARTICLES_PER_RUN=100` in `apps/api/.env.example`. That
makes a growing backlog a fact in a table instead of a surprise in three weeks.

---

## Carried Forward From `D2a`

- `D2a`'s completion gate was met, but the **verified baseline in `STATUS.md`
  was not updated by the worker** — it still described the `D1` run until a
  later commit fixed it. `docs/agents/workflow.md` makes updating that table the
  worker's job. Task 18 step 6 is yours. Do not skip it.
- `D2b` remains `not-started` and unspecified. Ambiguous matches continue to
  route to `needs_review`; nothing in this item changes that.
- The live database has two geocoded signals and zero events. After your first
  real `pipeline:run` that will change, and the numbers you record in the
  completion report are the first honest measurement of what the pipeline
  actually produces in a day.

---

## The Completion Gate

From `docs/agents/workflow.md`. `L` becomes `verified` only when all of these
are true, and it is not waived:

1. Every task in the plan is ticked in `STATUS.md`.
2. `corepack pnpm verify` ran and reported zero failures.
3. The real output of that run is quoted in the completion report — the actual
   test counts, not a claim that tests passed.
4. The report is committed and linked from `L`'s row in `ROADMAP.md`.
5. `STATUS.md`'s verified baseline is updated to the commit the run was
   performed at.

Never claim a gate passed without having run the command in that session. If the
run did not happen, the item stays `building`.

Set `L` to `building` in `ROADMAP.md` when task 1 begins. Do **not** set it to
`verified` yourself — hand back to the planner.
