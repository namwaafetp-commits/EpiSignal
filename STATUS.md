# Status — where the build is right now

Small and volatile by design. The long road is in [ROADMAP.md](ROADMAP.md); the
rules for who edits this file are in
[docs/agents/workflow.md](docs/agents/workflow.md).

**Last updated:** 2026-08-28

## Position

| Field | Value |
| --- | --- |
| Band | 3 — Product surface |
| Item | `E` — Signal Radar API, Signal Radar UI, admin monitoring |
| Status | `designing` |
| Briefing | [HANDOFF.md](HANDOFF.md) — still briefs `L`; it is rewritten when `E` is planned |
| Spec | Not yet committed |
| Plan | Not yet committed |

Last item completed: `L` — the scheduler, `verified` on 2026-08-28
([report](docs/reports/2026-08-28-subproject-l-report.md)). The planner re-ran
`corepack pnpm verify` at commit `4dbe028` before setting that status: exit code
0, 756 Python tests passed, 10 web tests passed, contracts diff clean, Next.js
build clean.

`E` is next because it is the only item downstream of `D2a` that does not wait
on an OpenRouter key. See **Blockers**.

## Next action

**Planner.** Brainstorm `E` into a design spec and commit it, then turn the spec
into a numbered plan, then archive [HANDOFF.md](HANDOFF.md) to
`docs/handoffs/2026-08-28-l.md` and rewrite it for `E`. No worker task exists
until the plan is committed.

Two questions the design has to answer before the plan can be written:

1. What `E` shows while extraction is blocked. The last runs on record left the
   backlog at `normalized=46`, `needs_review=7`, two geocoded signals, and zero
   events, so a radar built only on `events` renders nothing.
2. What to do with `feat/map-hero`. That unmerged branch already vendors a
   MapLibre map hero that draws `signal_locations` sized by recorded precision.
   It predates `D1` landing and is far behind `main`, so it is either salvaged
   deliberately into `E` or abandoned deliberately — not left hanging.

## Task ledger

Empty. `E` has no committed plan yet; the planner fills this section from the
plan's numbered tasks when it lands.

## Blockers

**The AI stage cannot run on this machine.** Every live `pipeline:run` fails at
`extract` with `EPISIGNAL_OPENROUTER_API_KEY is not set`
(`packages/backend/src/episignal_backend/schedule/stages.py:122`). The key is
absent from `apps/api/.env` and is not documented in `apps/api/.env.example`.
Consequence: the backlog stops at `normalized` — 46 signals at the last recorded
run — and `geocode` and `match` have nothing new to consume, so the corpus `L`
was built to grow does not grow. Adding the key is an operator action; it is not
work any item on the roadmap performs.

This blocks `D2b` and `F` outright. It does not block `E`, which reads what is
already stored.

Carried forward from `L`, still true: discovery stores up to 200 articles per
run while extraction handles 100, so the un-extracted backlog grows unless both
are matched in `.env`. `apps/api/.env.example` now sets
`EPISIGNAL_GDELT_MAX_ARTICLES_PER_RUN=100` for that reason.

## Verified baseline

Everything below was true at commit `76b8bb8` on `main`, tree clean. Recorded
from the `L` run logged untruncated in
[docs/reports/2026-08-28-subproject-l-report.md](docs/reports/2026-08-28-subproject-l-report.md).

| Fact | Value |
| --- | --- |
| Verification command | `corepack pnpm verify` — exit code 0 |
| Python tests | 756 passed, 1 warning |
| Web tests | 10 passed, 3 files |
| Lint and format | `ruff check` clean, 179 files formatted |
| Types | `mypy` clean across 92 source files |
| Migration revision | `20260828_0008_pipeline_runs` |
| Live database | `schema_check` passed — core tables + `pipeline_runs`, PostGIS up |
| Canonical diseases | 29 stable of 29 rows |
| Canonical sources | 2 stable and inactive |
| `pipeline:run` on live data | `ingest_who ok`, `ingest_ecdc ok`, `discover ok`, `dedupe ok`, `extract failed (RuntimeError)`, `geocode ok`, `match ok` |

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
