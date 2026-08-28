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
| Briefing | [HANDOFF.md](HANDOFF.md) |
| Spec | Not yet committed |
| Plan | Not yet committed |

Last item completed: `C2` — English title and the five-slot brief, `verified`
on 2026-08-28
([report](docs/reports/2026-08-28-subproject-c2-report.md)). The worker's gate at
`b26e794` passed with 789 Python tests and 10 web tests. The planner independently
re-ran `corepack pnpm verify` at `888369c` with the same counts and a clean
contract diff and production build, then confirmed the documentation-only
closure through `caefb6d` with `git diff --check` and a clean tree.

`C2` is taken before `E` on the operator's instruction that briefs read in
English as five bullets. An extraction is paid for once: fixing its shape now
means the corpus grows in its final form, and fixing it after `E` means paying a
second time for every article already read.

## Next action

**Planner.** Resume `E` design from the settled decisions below. Inspect the
current signal, event, location, and pipeline-run read seams; decide the smallest
honest radar contract; then commit the design spec before writing an
implementation plan. No worker task exists yet.

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

No `E` task ledger exists yet. The planner creates it only after the design spec
and implementation plan are approved and committed.

## Blockers

**None.** `C2` is verified. `E` is in design, not blocked.

## Verified baseline

Everything below was true at commit `b26e794` on `main`, tree clean. Recorded
from the `C2` run logged untruncated in
[docs/reports/2026-08-28-subproject-c2-report.md](docs/reports/2026-08-28-subproject-c2-report.md).

| Fact | Value |
| --- | --- |
| Verification command | `corepack pnpm verify` — exit code 0 |
| Python tests | 789 passed, 1 warning |
| Web tests | 10 passed, 3 files |
| Lint and format | `ruff check` clean, 181 files formatted |
| Types | `mypy` clean across 93 source files |
| Migration revision | `20260828_0008_pipeline_runs` |
| Live database | `db:check` passed — database=up, postgis=up |
| Canonical diseases | 29 stable of 29 rows |
| Canonical sources | 2 stable and inactive |
| Extraction schema | `extraction_schema_version: 2`, 5-slot brief, English title |
| Live extraction | `extract:signals -- --limit 10` — `classified=10 relevant=7 irrelevant=3 extracted=4 review=3 unavailable=0 requests=17 stopped_early=False` |
| Coherent evidence signal | `ec1cac1f-078a-45fe-8524-dacfa863c74c` |
| Live backfill | `extract:backfill -- --limit 10` — `examined=0 re_extracted=0 rejected=0 unavailable=0 storage_failed=0 requests=0 stopped_early=False` |

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
