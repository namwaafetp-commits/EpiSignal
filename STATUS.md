# Status — where the build is right now

Small and volatile by design. The long road is in [ROADMAP.md](ROADMAP.md); the
rules for who edits this file are in
[docs/agents/workflow.md](docs/agents/workflow.md).

**Last updated:** 2026-08-28

## Position

| Field | Value |
| --- | --- |
| Band | 2 — GDELT discovery layer |
| Item | `C2` — English title and the five-slot brief |
| Status | `planned` |
| Briefing | [HANDOFF.md](HANDOFF.md) |
| Spec | [2026-08-28-english-brief-design.md](docs/superpowers/specs/2026-08-28-english-brief-design.md) |
| Plan | [2026-08-28-english-brief.md](docs/superpowers/plans/2026-08-28-english-brief.md) |

Last item completed: `L` — the scheduler, `verified` on 2026-08-28
([report](docs/reports/2026-08-28-subproject-l-report.md)). The planner re-ran
`corepack pnpm verify` at commit `4dbe028` before setting that status: exit code
0, 756 Python tests passed, 10 web tests passed, contracts diff clean, Next.js
build clean.

`C2` is taken before `E` on the operator's instruction that briefs read in
English as five bullets. An extraction is paid for once: fixing its shape now
means the corpus grows in its final form, and fixing it after `E` means paying a
second time for every article already read.

## Next action

**Worker.** Start at task 1 below. Read [HANDOFF.md](HANDOFF.md) and the plan
first. Set `C2` to `building` in [ROADMAP.md](ROADMAP.md) when task 1 begins.

## Settled for `E`, so the next planner does not re-ask

- The homepage becomes the radar. `/` carries a large map of the last day or
  two, with a list beneath it ranked by recency and heat. `H` later refines that
  same page rather than replacing it with a second homepage.
- `E` renders briefs, so it follows `C2`.
- `feat/map-hero` is still unmerged and far behind `main`. It vendors a MapLibre
  hero that draws `signal_locations` sized by recorded precision — the map `E`
  needs. `E`'s design decides whether to salvage or abandon it; it is not left
  hanging a third time.
- Zero events exist, so a radar built only on `events` renders nothing. `E` is
  designed against signals, with events as the layer above them.

## Task ledger

From [docs/superpowers/plans/2026-08-28-english-brief.md](docs/superpowers/plans/2026-08-28-english-brief.md).
Tick each one in the same commit as its work.

- [x] 1. The slot vocabulary — `BriefSlot`, `BriefPoint`
- [x] 2. The extraction carries an English title and a brief
- [x] 3. Privacy scans the title and the brief
- [x] 4. The prompt asks for English and for five slots
- [ ] 5. The version, and reading what we already stored
- [ ] 6. Persistence stamps the version and writes the brief
- [ ] 7. Matching reads stored extractions tolerantly
- [ ] 8. The backfill selection
- [ ] 9. The backfill pass
- [ ] 10. The backfill runner
- [ ] 11. The command and the environment
- [ ] 12. The naming authority
- [ ] 13. Live verification and the completion report

Tasks 1 through 12 need no key, no network, and no database. Task 13 is the only
one that touches the database or spends money. Task 2 lands as a single commit:
removing `summary` from the contract breaks every payload in the suite at once.

## Blockers

**Cleared on 2026-08-28.** Every live `pipeline:run` used to fail at `extract`
with `EPISIGNAL_OPENROUTER_API_KEY is not set`
(`packages/backend/src/episignal_backend/schedule/stages.py:122`), which is why
the backlog stopped at `normalized` with 46 signals. The operator has since set
the key in `apps/api/.env`; its presence is confirmed, and the first live run
that exercises it will say whether extraction now completes.

`apps/api/.env.example` still does not document the variable. Task 11 of `C2`
adds it, with no value beside it.

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
