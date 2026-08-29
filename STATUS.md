# Status — where the build is right now

Small and volatile by design. The long road is in [ROADMAP.md](ROADMAP.md); the
rules for who edits this file are in
[docs/agents/workflow.md](docs/agents/workflow.md).

**Last updated:** 2026-08-29

## Position

| Field | Value |
| --- | --- |
| Band | 4 — Operations |
| Item | `M` — Manual review queue |
| Status | `planned` |
| Briefing | [HANDOFF.md](HANDOFF.md) |
| Spec | [2026-08-29-manual-review-queue-design.md](docs/superpowers/specs/2026-08-29-manual-review-queue-design.md) |
| Plan | [2026-08-29-manual-review-queue.md](docs/superpowers/plans/2026-08-29-manual-review-queue.md) |

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

**Worker.** Read `HANDOFF.md` and the committed `M` implementation plan. Create
`codex/manual-review-queue` in a separate worktree, run a clean baseline, then
start Task 1 test-first. Set `M` to `building` in the Task 1 commit and tick each
ledger item only in the commit that completes it. Stop after Task 15 and hand
the completion report back to the planner; do not mark `M` verified.

## Filed for the planner, so the next retarget sees it

Issue
[#1](https://github.com/namwaafetp-commits/EpiSignal/issues/1) — high-efficiency
pipeline (English-first discovery, pre-AI story grouping, 10-day event
follow-up) and the Gemini 2.5 Flash-Lite transition, filed `ready-for-agent` on
the operator's instruction on 2026-08-29 — is design work, not a plan. Its open
decisions (pre-AI grouping versus the verified dedupe and clustering stages,
adapter route versus a roster row, the updated flag against the existing
verification-status vocabulary, batch pricing verification) are settled in a
committed design spec before any roadmap row is added. Workers do not implement
from the issue; it enters the roadmap only through the planner.

## Settled for `M`, so the worker does not redesign it

- Open review cases are durable records with typed reasons, not a view inferred
  forever from nullable signal fields.
- One signal has at most one open case, but every closed case remains as audit
  history.
- Cause-specific resolution either requeues the existing pipeline, finalizes
  an event through shared rules, or sets terminal `dismissed`; no evidence is
  deleted or edited.
- Event-link choices are limited to candidate IDs and match scores stored when
  deterministic matching refused.
- A single bearer token protects review reads and writes. It is entered by the
  operator and kept only in browser component memory; no account system is in
  scope.
- Migration downgrade refuses to erase live review history.
- Live planning evidence was 37 review rows: 28 unresolved diseases, 7
  missing-text retrieval rows, 1 content-integrity quarantine, and 1 ambiguous
  event match. Re-query before migration; never hard-code these counts.

## Task ledger

- [ ] 1. Define review vocabularies and ORM shape.
- [ ] 2. Add reversible schema expansion and conservative backfill.
- [ ] 3. Define review commands, read models, and storage interface.
- [ ] 4. Persist typed case opening, queue reads, and automatic recovery.
- [ ] 5. Make every `needs_review` writer record a typed cause.
- [ ] 6. Extract one event-finalization implementation.
- [ ] 7. Resolve retry, disease, and dismissal cases transactionally.
- [ ] 8. Resolve ambiguous event cases through shared finalization.
- [ ] 9. Add secret admin authentication and safe configuration.
- [ ] 10. Expose authenticated queue reads.
- [ ] 11. Expose transactional resolution and regenerate contracts.
- [ ] 12. Strictly validate the review API in the web client.
- [ ] 13. Build the accessible cause-specific review queue.
- [ ] 14. Mount the admin page and navigation without widening scope.
- [ ] 15. Review, verify, capture safe live proof, and report.

## Blockers

**None.** `M` is planned and dependency-ready. Implementation has not started.

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
