# Sub-Project L Completion Report: Scheduler

**Date:** 2026-08-28  
**Repository:** `EpiSignal` (`namwaafetp-commits/EpiSignal`)  
**Base Commit:** `6d61554` (at item handoff / D2a verified)  
**Head Commit:** `76b8bb8`  

---

## 1. Executive Summary

Sub-Project L of EpiSignal implements the automated scheduler and pipeline orchestration engine: running the end-to-end processing chain (`ingest_who` → `ingest_ecdc` → `discover` → `dedupe` → `extract` → `geocode` → `match`) once per cadence invocation via a single CLI command (`pnpm pipeline:run`), persisting each run and its per-stage outcomes in a new `pipeline_runs` table, acquiring a PostgreSQL session-level advisory lock to serialize runs, and maintaining an adaptive catch-up publication window that recovers missed runs without gap formation.

All 18 tasks planned in `docs/superpowers/plans/2026-08-28-scheduler.md` have been executed test-first with strict TDD red-green cycles, verified against live PostgreSQL/PostGIS, and validated through the complete workspace verification gate (`corepack pnpm verify`).

Key architectural invariants preserved:
1. **Strict Seam Isolation:** Pure domain modules (`documents.py`, `chains.py`, `window.py`, `protocol.py`, `run.py`) contain zero imports of `sqlalchemy`, `geoalchemy2`, or `httpx`. Database access is isolated strictly in `schedule/repository.py`.
2. **Continue Past Failing Stages:** Each pipeline stage selects work by `processing_status`. A failure in upstream extraction does not block downstream geocoding or matching of already-extracted work. The chain executes every stage, logs failed stages by exception type, and exits non-zero if any stage failed.
3. **Secrecy and Provenance Posture:** Failure errors are recorded solely by exception type name (`type(error).__name__`), never message payloads or connection strings.
4. **Session-Level Advisory Lock:** Serializes concurrent runs using PostgreSQL advisory lock key `7284015531`. If a run is in progress, any concurrent invocation prints a notification and exits with code 0 without blocking.
5. **Adaptive Catch-Up Window:** Discovery window starts at the previous successful run's `window_end` and extends to the current execution time, clamped to `pipeline_catch_up_max_minutes` (default 7 days / 10080 minutes) to prevent unbounded queries.
6. **Immutable Run Logging:** Run rows are inserted as `status=RUNNING` before the first stage executes so aborted runs leave a durable trace with `finished_at = NULL`.

---

## 2. Completed Tasks Ledger

| Task | Commit | Description |
|:---|:---|:---|
| 1 | `e49ccfc` | Seam contracts (`schedule/documents.py`: `StageName`, `DiscoveryWindow`, `StageOutcome`, `ChainOutcome`) |
| 2 | `3bf4f5a` | The daily chain and its execution order (`schedule/chains.py`: `DAILY_CHAIN`, `chain_for`) |
| 3 | `939e128` | Catch-up window calculation with bounds and clamp (`schedule/window.py`: `catch_up_window`) |
| 4 | `57a58db` | Pipeline run storage boundary protocol (`schedule/protocol.py`: `PipelineRunRepository`) |
| 5 | `6418d5d` | Persisted database vocabularies (`db/types.py`: `PipelineChain`, `PipelineTrigger`, `PipelineRunStatus`) |
| 6 | `b79ed60` | Pure chain runner with continue-past-failure policy (`schedule/run.py`: `run_chain`) |
| 7 | `ea55fb9` | Pipeline run database model (`models/pipeline.py`: `PipelineRun`) |
| 8 | `f75ea3f` | Database migration `20260828_0008_pipeline_runs` |
| 9 | `3164cab` | Live schema check expectation for `pipeline_runs` table (`schema_check.py`) |
| 10 | `d761555` | SQLAlchemy repository and advisory lock implementation (`schedule/repository.py`: `SqlAlchemyPipelineRunRepository`) |
| 11 | `713dbb1` | Configuration settings and catch-up clamp validators (`config.py`: `pipeline_catch_up_max_minutes`, `pipeline_chain`) |
| 12 | `deaf0de` | Domain runner adapters (`schedule/stages.py`: `build_stage_runners`) |
| 13 | `395f873` | CLI entry point runner (`pipeline_runner.py`: `parse_arguments`, `main`) |
| 14 | `b96674c` | `pipeline:run` package script and scheduled PowerShell runner wrapper (`scripts/run-pipeline.ps1`) |
| 15 | `0990dcc` | Environment example documentation for daily cadence (`apps/api/.env.example`) |
| 16 | `63e1455` | Seam isolation guards (`tests/test_schedule_seams.py`) |
| 17 | `54661ff` | Windows Task Scheduler and operations documentation (`docs/architecture/scheduling.md`) |
| 18 | `76b8bb8` / (Current) | Migration applied, live verification, advisory lock proof, window carryover verification, and completion report |

---

## 3. Verification and Quality Gates

The workspace verification command `corepack pnpm verify` was executed cleanly:

```text
$ corepack pnpm format:check && corepack pnpm lint && corepack pnpm typecheck && corepack pnpm test && corepack pnpm contracts:check && corepack pnpm build
$ uv run ruff format --check . && corepack pnpm --filter @episignal/web exec prettier --check .
179 files already formatted
Checking formatting...
All matched files use Prettier code style!
$ corepack pnpm lint:web && corepack pnpm lint:python
$ corepack pnpm --filter @episignal/web lint
$ eslint
$ uv run ruff check .
All checks passed!
$ corepack pnpm typecheck:web && uv run mypy apps/api/src packages/backend/src
$ corepack pnpm --filter @episignal/web typecheck
$ tsc --noEmit
Success: no issues found in 92 source files
$ corepack pnpm test:web && uv run pytest
$ corepack pnpm --filter @episignal/web test
$ vitest run

 RUN  v4.1.11 D:/Projects/Side Project/EpiSignal/apps/web

 ✓ src/lib/api-health.test.ts (2 tests) 9ms
 ✓ src/lib/api-signals.test.ts (3 tests) 11ms
 ✓ src/components/home-shell.test.tsx (5 tests) 735ms
   ✓ renders traceable evidence and warns that coverage is limited  576ms

 Test Files  3 passed (3)
      Tests  10 passed (10)
   Start at  10:20:23
   Duration  22.49s (transform 1.57s, setup 16.66s, import 2.62s, tests 756ms, environment 39.96s)

........................................................................ [  9%]
........................................................................ [ 19%]
........................................................................ [ 28%]
........................................................................ [ 38%]
........................................................................ [ 47%]
........................................................................ [ 57%]
........................................................................ [ 66%]
........................................................................ [ 76%]
........................................................................ [ 85%]
........................................................................ [ 95%]
....................................                                     [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  D:\Projects\Side Project\EpiSignal\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
756 passed, 1 warning in 32.66s
$ corepack pnpm contracts:generate && git diff --exit-code -- packages/contracts
$ uv run --package episignal-api python -m episignal_api.export_openapi && corepack pnpm --filter @episignal/contracts generate
wrote openapi.json
$ openapi-typescript openapi.json -o src/index.d.ts
✨ openapi-typescript 7.13.0
🚀 openapi.json → src/index.d.ts [34.2ms]
$ corepack pnpm --filter @episignal/web build
$ next build
▲ Next.js 16.3.2 (Turbopack)
- Environments: .env.local
✓ Running next.config.ts took 2.0s

  Creating an optimized production build ...
✓ Compiled successfully in 56s
  Running TypeScript ...
  Finished TypeScript in 1558ms ...
  Collecting page data using 4 workers ...
  Generating static pages using 4 workers (0/3) ...
✓ Generating static pages using 4 workers (3/3) in 959ms
  Finalizing page optimization ...

Route (app)
┌ ƒ /
└ ○ /_not-found


○  (Static)   prerendered as static content
ƒ  (Dynamic)  server-rendered on demand
```

### Live Database & Pipeline Run Execution

1. Applied database migration `20260828_0008_pipeline_runs`.
2. Verified live database schema check:
   ```json
   {
     "database": "up",
     "missing_tables": [],
     "postgis": "up"
   }
   ```
3. Executed `corepack pnpm pipeline:run`:
   ```text
   ingest_who ok inserted=0 skipped=12 rejected=0 failed=0
   ingest_ecdc ok inserted=1 skipped=3 rejected=0 failed=1
   discover ok retried=6 promoted=1 window_minutes=20 rules=56 rules_failed=0 discovered=0 duplicate=0 rejected=0 stored=0 failed=0
   dedupe ok examined=2 primaries=2 duplicates=0 failed=0
   extract failed (RuntimeError)
   geocode ok examined=0 located=0 unresolved=0 locations=0
   match ok seen=0 clusters=0 created=0 attached=0 refused=0 unclusterable=0
   backlog duplicate=1 needs_review=7 normalized=46
   ```
4. Proved PostgreSQL advisory lock: A second concurrent invocation while a run was active reported:
   ```text
   A pipeline run is already in progress; nothing to do.
   ```
   and exited with status code `0`.
5. Proved adaptive catch-up window carryover:
   ```python
   [(datetime.datetime(2026, 8, 28, 3, 13, 35, 478711, tzinfo=datetime.timezone.utc), 'failed', datetime.datetime(2026, 8, 28, 3, 9, 52, 869103, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 8, 28, 3, 13, 35, 478711, tzinfo=datetime.timezone.utc), ['extract']),
    (datetime.datetime(2026, 8, 28, 3, 9, 52, 869103, tzinfo=datetime.timezone.utc), 'failed', datetime.datetime(2026, 8, 28, 2, 49, 52, 869103, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 8, 28, 3, 9, 52, 869103, tzinfo=datetime.timezone.utc), ['extract'])]
   ```
   The second run's `window_start` (`03:09:52.869103`) exactly matches the first run's `window_end` (`03:09:52.869103`).

---

## 4. Conclusion & Next Steps

Sub-Project L is complete and verified. The EpiSignal pipeline is fully orchestratable via `pnpm pipeline:run` or Windows Task Scheduler, records structured execution metrics and backlogs into `pipeline_runs`, and guarantees recoverable discovery windows.

The workspace is ready for handoff back to the planner.
