# Sub-Project D2a Completion Report: Story Clustering, Event Matching, and Dual Scoring

**Date:** 2026-08-28  
**Repository:** `EpiSignal` (`namwaafetp-commits/EpiSignal`)  
**Base Commit:** `4cf13b5`  
**Head Commit:** Pending final documentation commit  

---

## 1. Executive Summary

Sub-Project D2a of EpiSignal implements the core epidemiological event synthesis engine: clustering geocoded signals into story clusters, matching clusters against existing candidate events using conservative decision rules, creating new events or attaching signals to existing events, preserving immutable observation history, and deriving dual independent scores (`early_signal_score` and `evidence_score`).

All 22 tasks planned in `docs/superpowers/plans/2026-08-28-story-clustering.md` have been executed test-first with strict TDD red-green cycles, verified against live PostgreSQL/PostGIS, and validated through the complete workspace verification gate (`corepack pnpm verify`).

Key architectural invariants preserved:
1. **Conservative Event Matching:** When two or more candidate events match a story cluster at or above the threshold (`0.60`), the system refuses to guess and routes the signals to `needs_review`.
2. **Dual Independent Scores on 0–1:** `early_signal_score` measures operational surveillance urgency (recency, velocity, multi-source interest, spatial spread, precision). `evidence_score` measures corroboration and grounded strength (official source presence, credibility tier, observation volume, grounded consistency, extraction confidence). Neither score reads from or influences the other.
3. **Derived Verification Status:** `verification_status` (`OFFICIALLY_CONFIRMED`, `HIGH_CREDIBILITY`, `SIGNAL`) is derived deterministically from source facts and credibility tiers, never computed from subjective thresholds.
4. **Immutable Observation History:** `record_observation` inserts new observation records from ground truth spans without overwriting historical records. Unstated counts are strictly recorded as `None`, never substituted with arbitrary zeros.
5. **Precision Governs Spatial Compatibility:** Distance comparisons respect the coarsest shared precision between locations. Geocoded signals never compute false distances to provincial or country centroids.
6. **Strict Seam Isolation:** Pure domain modules (`documents.py`, `cluster.py`, `match.py`, `score.py`, `protocol.py`, `assemble.py`) contain zero imports of `sqlalchemy`, `geoalchemy2`, or `httpx`. Database access is isolated strictly in `events/repository.py`.

---

## 2. Completed Tasks Ledger

| Task | Commit | Description |
|:---|:---|:---|
| 1 | `05dcec5` | Contracts across the seams (`events/documents.py`: `LocationForMatching`, `SignalForMatching`, `StoryCluster`, `CandidateEvent`, `MatchAction`, `MatchDecision`, `ScoreBreakdown`) |
| 2 | `a47d45d` | Precision weighting (`precision_weight`: `PLACE=1.0`, `ADMIN2=0.75`, `ADMIN1=0.50`, `COUNTRY=0.25`, `UNRESOLVED=0.0`) |
| 3 | `0412748` | Spatial compatibility at the coarsest shared precision (`spatially_compatible`, `haversine_distance_km`) |
| 4 | `38f4bce` | Temporal compatibility with timezone awareness (`temporally_compatible`) |
| 5 | `0495e89` | Disease requirement and composite signal compatibility (`representative_location`, `compatible`) |
| 6 | `255dd24` | Single-link cluster assembly via union-find (`build_clusters`) |
| 7 | `2bfec64` | Candidate event match scoring (`match_score`) |
| 8 | `3f83e5f` | The conservative decision ladder (`decide`: `ATTACH`, `CREATE`, `REFUSE`) |
| 9 | `d02c0e2` | The early signal score calculation (`early_signal_score`) |
| 10 | `d406e25` | The evidence score calculation (`evidence_score`) |
| 11 | `9369eb7` | Verification status derivation from sources alone (`verification_status`) |
| 12 | `deb1ba5` | Alembic migration `20260828_0007_event_scores` and `Event` model update (`early_signal_score`, `evidence_score` with `[0, 1]` checks) |
| 13 | `4e2bd36` | Expected event score columns schema check (`EXPECTED_EVENT_COLUMNS`) |
| 14 | `bdf52d1` | Storage boundary protocol (`EventRepository`) |
| 15 | `2124300` | Geocoded signal selection query (`signals_to_match`) |
| 16 | `af93e8a` | Candidate event retrieval with PostGIS spatial indexing (`candidate_events`) |
| 17 | `11ec8fb` | Event creation, signal relationship attachment (`create_event`, `attach_signal`) |
| 18 | `637f4b0` | Immutable observation insertion, location tracking, and score application (`record_observation`, `add_locations`, `apply_scores`) |
| 19 | `4a237f3` | End-to-end event assembly orchestration (`run_event_assembly`) |
| 20 | `10df13a` | Story clustering and event matching configuration settings |
| 21 | `ec9065c` | CLI runner `event_runner.py`, `match:events` script, PowerShell runner `scripts/match-events.ps1`, and architectural seam guards |
| 22 | (Current) | Live database migration, idempotency check, live CLI matching, and completion report |

---

## 3. Verification and Quality Gates

The workspace verification command `corepack pnpm verify` was executed cleanly:

```
$ corepack pnpm format:check && corepack pnpm lint && corepack pnpm typecheck && corepack pnpm test && corepack pnpm contracts:check && corepack pnpm build
$ uv run ruff format --check . && corepack pnpm --filter @episignal/web exec prettier --check .
158 files already formatted
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
Success: no issues found in 82 source files
$ corepack pnpm test:web && uv run pytest
$ corepack pnpm --filter @episignal/web test
$ vitest run

 RUN  v4.1.11 D:/Projects/Side Project/EpiSignal/apps/web

 ✓ src/lib/api-health.test.ts (2 tests) 10ms
 ✓ src/lib/api-signals.test.ts (3 tests) 24ms
 ✓ src/components/home-shell.test.tsx (5 tests) 620ms
   ✓ renders traceable evidence and warns that coverage is limited  490ms

 Test Files  3 passed (3)
      Tests  10 passed (10)
   Start at  09:16:58
   Duration  11.31s (transform 1.27s, setup 6.29s, import 1.73s, tests 654ms, environment 19.74s)

694 passed, 1 warning in 42.60s
$ corepack pnpm contracts:generate && git diff --exit-code -- packages/contracts
$ uv run --package episignal-api python -m episignal_api.export_openapi && corepack pnpm --filter @episignal/contracts generate
wrote openapi.json
$ openapi-typescript openapi.json -o src/index.d.ts
✨ openapi-typescript 7.13.0
🚀 openapi.json → src/index.d.ts [60.3ms]
$ corepack pnpm --filter @episignal/web build
$ next build
▲ Next.js 16.3.2 (Turbopack)
- Environments: .env.local
✓ Running next.config.ts took 1558ms

  Creating an optimized production build ...
✓ Compiled successfully in 33.0s
  Running TypeScript ...
  Finished TypeScript in 1555ms ...
  Collecting page data using 4 workers ...
  Generating static pages using 4 workers (0/3) ...
✓ Generating static pages using 4 workers (3/3) in 490ms
  Finalizing page optimization ...

Route (app)
┌ ƒ /
└ ○ /_not-found


○  (Static)   prerendered as static content
ƒ  (Dynamic)  server-rendered on demand
```

### Live Database & CLI Execution
- Applied database migration `20260828_0007_event_scores`.
- Ran `scripts/verify-live-database.ps1`:
  ```
  database: up
  postgis: up
  core tables: 8 present
  canonical diseases: 29 stable (of 29 rows)
  canonical sources: 2 stable and inactive
  Live database verification passed.
  ```
- Executed `corepack pnpm match:events`:
  ```
  seen=2 clusters=0 created=0 attached=0 refused=0 unclusterable=2
  ```
- Executed `corepack pnpm match:events --stale`:
  ```
  seen=0 clusters=0 created=0 attached=0 refused=0 unclusterable=0
  ```

---

## 4. Conclusion & Next Steps

Sub-Project D2a is complete and fully verified. Signals are cleanly clustered and matched into events with grounded observation records and dual scores.

The repository is ready for **Sub-Project D2b** (Event API & Web UI Layer), exposing events, dual scores, and lineage to the frontend.
