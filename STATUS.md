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
| Status | `building` |
| Briefing | [HANDOFF.md](HANDOFF.md) |
| Spec | [2026-08-28-english-brief-design.md](docs/superpowers/specs/2026-08-28-english-brief-design.md) |
| Plan | [2026-08-28-c2-completion-corrections.md](docs/superpowers/plans/2026-08-28-c2-completion-corrections.md) |

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

**Worker.** Execute the five correction tasks in
[the correction plan](docs/superpowers/plans/2026-08-28-c2-completion-corrections.md),
starting with committed-outcome accounting. `C2` is already `building`; do not
edit `ROADMAP.md` or `HANDOFF.md`. Hand back after the corrected report is
committed and the tree is clean.

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
- [x] 5. The version, and reading what we already stored
- [x] 6. Persistence stamps the version and writes the brief
- [x] 7. Matching reads stored extractions tolerantly
- [x] 8. The backfill selection
- [x] 9. The backfill pass
- [x] 10. The backfill runner
- [x] 11. The command and the environment
- [x] 12. The naming authority
- [ ] 13. Live verification and the completion report — reopened by planner review

Tasks 1 through 12 need no key, no network, and no database. Task 13 is the only
one that touches the database or spends money. Task 2 lands as a single commit:
removing `summary` from the contract breaks every payload in the suite at once.

### C2 correction ledger

From
[docs/superpowers/plans/2026-08-28-c2-completion-corrections.md](docs/superpowers/plans/2026-08-28-c2-completion-corrections.md).
Tick each item in the same commit as its work.

- [x] 1. Count only committed extraction outcomes
- [x] 2. Make the backfill command fail honestly
- [x] 3. Enforce the ISO 639-1 vocabulary
- [ ] 4. Make accepted fixtures source-backed
- [ ] 5. Replace incomplete completion evidence

## Blockers

**None external.** Planner review found four completion defects: false-success
backfill exits, pre-commit success accounting, syntax-only language validation,
and provenance-invalid completion evidence. `C2` stays `building` until the
correction plan passes re-review.

## Verified baseline

Everything below was true at commit `5e148ce` on `main`, tree clean. Recorded
from the `C2` run logged untruncated in
[docs/reports/2026-08-28-subproject-c2-report.md](docs/reports/2026-08-28-subproject-c2-report.md).

| Fact | Value |
| --- | --- |
| Verification command | `corepack pnpm verify` — exit code 0 |
| Python tests | 783 passed, 1 warning |
| Web tests | 10 passed, 3 files |
| Lint and format | `ruff check` clean, 181 files formatted |
| Types | `mypy` clean across 93 source files |
| Migration revision | `20260828_0008_pipeline_runs` |
| Live database | `db:check` passed — database=up, postgis=up |
| Canonical diseases | 29 stable of 29 rows |
| Canonical sources | 2 stable and inactive |
| Extraction schema | `extraction_schema_version: 2`, 5-slot brief, English title |
| Live backfill | `extract:backfill` passed, version stamped in PostgreSQL |

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
