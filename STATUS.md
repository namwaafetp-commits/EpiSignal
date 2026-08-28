# Status — where the build is right now

Small and volatile by design. The long road is in [ROADMAP.md](ROADMAP.md); the
rules for who edits this file are in
[docs/agents/workflow.md](docs/agents/workflow.md).

**Last updated:** 2026-08-28

## Position

| Field | Value |
| --- | --- |
| Band | 4 — Operations |
| Item | `L` — Scheduler |
| Status | `planned` |
| Briefing | [HANDOFF.md](HANDOFF.md) |
| Spec | [2026-08-28-scheduler-design.md](docs/superpowers/specs/2026-08-28-scheduler-design.md) |
| Plan | [2026-08-28-scheduler.md](docs/superpowers/plans/2026-08-28-scheduler.md) |

Last item completed: `D2a` — story clustering, event matching, and dual scoring,
`verified` on 2026-08-28
([report](docs/reports/2026-08-28-subproject-d2a-report.md)).

`L` is taken out of Band 4 order deliberately. Every pipeline stage is verified
and every one is invoked by hand, which is why the live database holds two
geocoded signals and zero events. `D2b` would tune an embedding threshold
against zero refusals and `E` would render an empty list; both need the corpus
that running daily produces.

## Next action

**Worker.** Start at task 1 below. Read [HANDOFF.md](HANDOFF.md) and the plan
first. Set `L` to `building` in [ROADMAP.md](ROADMAP.md) when task 1 begins.

## Task ledger

From [docs/superpowers/plans/2026-08-28-scheduler.md](docs/superpowers/plans/2026-08-28-scheduler.md).
Tick each one in the same commit as its work.

- [x] 1. Contracts across the seams — `schedule/documents.py`
- [x] 2. The daily chain and its order
- [x] 3. The catch-up window
- [x] 4. The `PipelineRunRepository` boundary
- [x] 5. The persisted vocabularies
- [x] 6. The chain runner and its failure policy
- [x] 7. The `PipelineRun` model
- [x] 8. The migration `20260828_0008_pipeline_runs`
- [x] 9. The schema check knows the new table
- [x] 10. The repository and the advisory lock
- [x] 11. Settings and the catch-up clamp
- [x] 12. The stage adapters
- [x] 13. The runner — `pipeline_runner.py`
- [x] 14. The script and the shell wrapper
- [x] 15. The environment example
- [x] 16. The seam guard
- [x] 17. The scheduling document
- [ ] 18. Live verification and the completion report

Tasks 1 through 17 need no key, no network, and no database. Task 18 is the only
one that touches the database.

## Blockers

None. `L` is planned and ready to execute.

Decisions already settled, so the worker does not reopen them:

- The OS drives the cadence. One-shot CLI plus a Windows Task Scheduler entry.
  No APScheduler, no Celery, no daemon, no queue. Phase 1 §42.
- One chain, `daily`, in the order the spec gives. WHO and ECDC are ingested
  first so an official document that corroborates a story is in the database
  before that story's media coverage is matched.
- A failing stage does not stop the chain. Every stage selects its own backlog
  by `processing_status`, so the run continues, records which stages failed, and
  exits non-zero.
- Runs are recorded in a new `pipeline_runs` table, not in stdout alone.
  Journald does not exist on Windows and item `E` needs a table to render.
- The daily cadence lives in `apps/api/.env.example`, not in `config.py`
  defaults. The existing `window_covers_the_interval` validator already enforces
  the relationship between the window and the interval.

Known trap, carried into the plan rather than fixed by changing defaults:
discovery stores up to 200 articles per run while extraction handles 100, so at
the current defaults a daily run grows the un-extracted backlog by 100 a day.
Task 10 records backlog depth on every run and task 15 recommends matching the
two in `.env`.

## Verified baseline

Everything below was true at commit `0b777bc` on `main`, tree clean. Recorded
from the `D2a` run logged untruncated in
[docs/reports/2026-08-28-subproject-d2a-report.md](docs/reports/2026-08-28-subproject-d2a-report.md).

| Fact | Value |
| --- | --- |
| Verification command | `corepack pnpm verify` — exit code 0 |
| Python tests | 694 passed, 1 warning |
| Web tests | 10 passed, 3 files |
| Lint and format | `ruff check` clean, 158 files formatted |
| Types | `mypy` clean across 82 source files |
| Migration revision | `20260828_0007_event_scores` |
| Live database | `scripts/verify-live-database.ps1` passed — 8 core tables, PostGIS up |
| Canonical diseases | 29 stable of 29 rows |
| Canonical sources | 2 stable and inactive |
| `match:events` on live data | `seen=2 clusters=0 created=0 attached=0 refused=0 unclusterable=2` |

Reproduce with:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src packages/backend/src
corepack pnpm verify
```

Update this table only from a run you actually performed, and record the commit
it was performed at.
