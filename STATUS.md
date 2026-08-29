# Status — where the build is right now

Small and volatile by design. The long road is in [ROADMAP.md](ROADMAP.md); the
rules for who edits this file are in
[docs/agents/workflow.md](docs/agents/workflow.md).

**Last updated:** 2026-08-29

## Position

| Field | Value |
| --- | --- |
| Band | 3 — Product surface |
| Item | `E` — Signal Radar API, Signal Radar UI, admin monitoring |
| Status | `verified` |
| Briefing | [HANDOFF.md](HANDOFF.md) |
| Spec | [2026-08-28-signal-radar-design.md](docs/superpowers/specs/2026-08-28-signal-radar-design.md) |
| Plan | [2026-08-28-signal-radar.md](docs/superpowers/plans/2026-08-28-signal-radar.md) |
| Report | [2026-08-28-subproject-e-report.md](docs/reports/2026-08-28-subproject-e-report.md) |

Last item completed: `E` — Signal Radar API, Signal Radar UI, and admin
monitoring, `verified` on 2026-08-29
([report](docs/reports/2026-08-28-subproject-e-report.md)). All 15 plan tasks are
ticked. The completion report records its zero-failure gate, including 828
Python tests and 58 web tests across 8 files. The planner independently re-ran
`corepack pnpm verify` at `2499e4e` on `main`: 848 Python tests and 58 web tests
across 8 files passed, Ruff and ESLint were clean, mypy and tsc were clean
across 97 source files, the contract diff was clean, and the Next production
build succeeded.

The extraction stall was then fixed on `main`. Structured outputs now reach
geocoding and event assembly; the live proof recorded 28 extracted signals with
zero shape rejections, 32 geocoded signals, and the first 3 events.

## Next action

**Planner.** Choose the next dependency-ready item, design it, write its
implementation plan, archive this `E` briefing, and retarget `HANDOFF.md` and
the task ledger together. Do not begin implementation in the planner role.

## Settled by `E`, so later work does not re-ask

- The homepage becomes the radar. `/` carries a large map of the last day or
  two, with a list beneath it ranked by recency and heat. `H` later refines that
  same page rather than replacing it with a second homepage.
- `E` renders briefs, so it follows `C2`.
- `feat/map-hero` is superseded. `E` shipped its own smaller MapLibre module and
  deliberately did not merge or copy the branch's generic map module. Retire
  the branch and worktree after operator approval.
- The radar is signal-first, with events as optional context above signals. It
  remains useful while the event table is sparse.

## Task ledger

- [x] 1. Preserve exception types in pipeline history.
- [x] 2. Define the radar read contracts and representative location rule.
- [x] 3. Query and assemble recent radar signals.
- [x] 4. Query counts-only pipeline history.
- [x] 5. Expose `GET /api/v1/radar`.
- [x] 6. Expose `GET /api/v1/admin/pipeline-runs`.
- [x] 7. Regenerate and lock the API contracts.
- [x] 8. Strictly validate radar responses in the web client.
- [x] 9. Add only the map dependencies and pure marker helpers.
- [x] 10. Mount a small resilient MapLibre component.
- [x] 11. Replace the homepage with the radar map and list.
- [x] 12. Wire server fetching, loading, responsive CSS, and build safety.
- [x] 13. Strictly validate pipeline history in the web client.
- [x] 14. Build the read-only pipeline monitor page.
- [x] 15. Review, run the full gate, capture live proof, and write the report.

## Blockers

**None.** `E` is verified. Next-item selection is planner work.

## Verified baseline

Everything below was true at commit `2499e4e` on `main`, tree clean. Recorded
from the extraction stall resolution run logged untruncated in
[docs/reports/2026-08-28-extraction-stall-fix-report.md](docs/reports/2026-08-28-extraction-stall-fix-report.md).

| Fact | Value |
| --- | --- |
| Verification command | `corepack pnpm verify` — exit code 0 |
| Python tests | 848 passed, 1 warning |
| Web tests | 58 passed, 8 files |
| Lint and format | `ruff check` and `eslint` clean, 190 files formatted |
| Types | `tsc` and `mypy` clean across 97 source files |
| Migration revision | `20260828_0009_quarantine_corrupted_signal` |
| Live database | `db:check` passed — database=up, postgis=up |
| Canonical diseases | 29 stable of 29 rows |
| Canonical sources | 2 stable and inactive |
| Extraction schema | `extraction_schema_version: 2`, 5-slot brief, English title, OpenRouter structured outputs (`json_schema`) |
| Model ladder | `deepseek/deepseek-chat` (T1), `mistralai/mistral-small-24b-instruct-2501` (T2), `anthropic/claude-haiku-4.5` (T3) |
| Radar endpoints | `GET /api/v1/radar`, `GET /api/v1/admin/pipeline-runs` |
| Live extraction & pipeline proof | 28 signals extracted in live run (0 shape rejections), 32 geocoded, 3 events created (EVT-EEA92838, EVT-1BAC05A1, EVT-F00791B8) |

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
