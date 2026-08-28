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
| Status | `planned` |
| Briefing | [HANDOFF.md](HANDOFF.md) |
| Spec | [2026-08-28-signal-radar-design.md](docs/superpowers/specs/2026-08-28-signal-radar-design.md) |
| Plan | [2026-08-28-signal-radar.md](docs/superpowers/plans/2026-08-28-signal-radar.md) |

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

**Worker.** Read `HANDOFF.md` and the committed `E` implementation plan. Start
Task 1 test-first, set `E` to `building` in `ROADMAP.md`, and tick each task in
this ledger in the same commit as the work. Stop after Task 15 and hand the
verified report back to the planner; do not mark `E` verified.

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

**None.** `E` implementation and verification gate complete.

## Verified baseline

Everything below was true at commit `1a31480` on `main`, tree clean. Recorded
from the `E` run logged untruncated in
[docs/reports/2026-08-28-subproject-e-report.md](docs/reports/2026-08-28-subproject-e-report.md).

| Fact | Value |
| --- | --- |
| Verification command | `corepack pnpm verify` — exit code 0 |
| Python tests | 829 passed, 1 warning |
| Web tests | 58 passed, 8 files |
| Lint and format | `ruff check` and `eslint` clean, 187 files formatted |
| Types | `tsc` and `mypy` clean across 96 source files |
| Migration revision | `20260828_0008_pipeline_runs` |
| Live database | `db:check` passed — database=up, postgis=up |
| Canonical diseases | 29 stable of 29 rows |
| Canonical sources | 2 stable and inactive |
| Extraction schema | `extraction_schema_version: 2`, 5-slot brief, English title |
| Radar endpoints | `GET /api/v1/radar`, `GET /api/v1/admin/pipeline-runs` |
| Live radar proof | `hours=168, limit=10` — 5 signals retrieved, 5-slot briefs, 0 raw-text leak |
| Live pipeline monitor proof | 2 runs recorded, safe failure stages, counts-only |

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
