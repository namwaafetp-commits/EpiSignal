# Status — where the build is right now

Small and volatile by design. The long road is in [ROADMAP.md](ROADMAP.md); the
rules for who edits this file are in
[docs/agents/workflow.md](docs/agents/workflow.md).

**Last updated:** 2026-08-28

## Position

| Field | Value |
| --- | --- |
| Band | 2 — GDELT discovery layer |
| Item | `D2a` — Story clustering, event matching, dual scoring |
| Status | `planned` |
| Briefing | [HANDOFF.md](HANDOFF.md) |
| Spec | [2026-08-28-story-clustering-design.md](docs/superpowers/specs/2026-08-28-story-clustering-design.md) |
| Plan | [2026-08-28-story-clustering.md](docs/superpowers/plans/2026-08-28-story-clustering.md) |

Last item completed: `D1` — geocoding, `verified` on 2026-08-27
([report](docs/reports/2026-08-27-subproject-d1-report.md)).

## Next action

**Worker.** Start at task 1 below. Read [HANDOFF.md](HANDOFF.md) and the plan
first. Set `D2a` to `building` in [ROADMAP.md](ROADMAP.md) when task 1 begins.

## Task ledger

From [docs/superpowers/plans/2026-08-28-story-clustering.md](docs/superpowers/plans/2026-08-28-story-clustering.md).
Tick each one in the same commit as its work.

- [x] 1. Contracts across the seams — `events/documents.py`
- [x] 2. Precision weighting
- [x] 3. Spatial compatibility at the coarsest shared precision
- [x] 4. Temporal compatibility
- [x] 5. A signal with no disease is not clustered
- [x] 6. Single-link cluster assembly
- [x] 7. Candidate match scoring
- [x] 8. The conservative decision — attach, create, or refuse
- [x] 9. The early signal score
- [x] 10. The evidence score
- [x] 11. Verification status is derived, never scored
- [x] 12. The score column migration `20260828_0007_event_scores`
- [x] 13. Schema check follows the rename
- [x] 14. The `EventRepository` boundary
- [x] 15. Selecting geocoded signals
- [x] 16. Candidate event retrieval
- [x] 17. Creating events and attaching signals
- [x] 18. Observations are inserted, never updated
- [x] 19. The assembly pass — `run_event_assembly`
- [x] 20. Configuration
- [x] 21. The runner, the script, and the seam guard
- [x] 22. Live database verification and the completion report

Tasks 1 through 21 need no key, no network, and no database. Task 22 is the only
one that touches the database.

## Blockers

None. `D2a` is planned and ready to execute.

Decisions already settled, so the worker does not reopen them:

- Both scores are `0–1`. `events.attention_score` is renamed to
  `early_signal_score` and `confidence_score` to `evidence_score` in task 12,
  with both check constraints widened to `0–1`. The table is empty, so nothing
  moves.
- Scoring is a deterministic weighted formula over stored fields. No model call
  anywhere in `D2a`.
- A cluster matching two events at or above the threshold creates nothing and
  routes its signals to `needs_review`. Embedding and LLM answers for those
  cases are `D2b`, not this item.

Carried-forward follow-ups from `C` are listed in [HANDOFF.md](HANDOFF.md) and
are not blockers.

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
