# Handoff — Sub-Project D2: Story Clustering, Event Matching, and Dual Scoring

**Date:** 2026-08-27  
**Branch:** `main` (clean, 618 passing tests)  
**Head:** Sub-project D1 complete and verified; `signal_locations` exists and is populated with PostGIS geometry and GIST indexing.  
**State:** Sub-projects A, B, C, and D1 are complete, verified, and merged. **Your task is to design, plan, and implement Sub-Project D2: Story Clustering, Event Matching, and Dual Scoring.**  

---

## What Sub-Project D2 Builds

Sub-project D2 completes the event aggregation and intelligence core of EpiSignal:

1. **Story Clustering:** Groups related signals reporting on the same underlying outbreak cluster across time, disease, and geography (`signal_locations`).
2. **Event Matching & Creation:** Evaluates whether a story cluster matches an existing `events` record or represents a new emerging event (`event_signals`, `event_observations`, `event_locations`). Transitions signals to `processing_status = 'matched'`.
3. **Dual Scoring Engine:** Computes the two unmerged scores required by `CONTEXT.md`:
   - `early_signal_score`: Speed, velocity, syndromic anomaly strength, source diversity, and geographic spread.
   - `evidence_score`: Official source confirmation, lab backing, observational density, and data consistency.
4. **Observation History Tracking:** Records metric snapshots over time in `event_observations` without overwriting historical claims.

---

## Start Here

Read in this exact order:

1. This file (`HANDOFF.md`);
2. `AGENTS.md` — model routing, project skills, TDD rules, token efficiency, provenance principles;
3. `CONTEXT.md` — the naming authority. Use signal, primary, event, observation, location role, early signal score, evidence score, and verification status exactly as defined there;
4. `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md` — the umbrella architecture and its invariants;
5. `docs/reports/2026-08-27-subproject-d1-report.md` — Sub-project D1's completion report;
6. `docs/reports/2026-08-27-subproject-c-report.md` — Sub-project C's completion report;
7. `report.md` — Sub-project B's completion report.

---

## Windows Environment Facts

- **Python:** Run all commands through `uv run`. Do not activate virtual environments manually. Bare `python` is not on `PATH`; use `uv run python`.
- **Node / pnpm:** `pnpm` is not on `PATH`, but `corepack` ships with Node and is. Always enter the workspace through `corepack pnpm <command>` (for example `corepack pnpm verify`, `corepack pnpm db:migrate`, `corepack pnpm geocode:signals`).
- **PowerShell:** Commands run under Windows PowerShell 5.1 (no `&&`, no ternary, no `??`). Chain with `;`.
- **UTF-8 BOM:** Strip UTF-8 BOM from generated scripts or use standard python writers.

---

## Verified Baseline

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src packages/backend/src
corepack pnpm verify
```

**Expected baseline output:**
- `618 passed, 1 warning`
- `All checks passed!`
- `139 files already formatted`
- `Success: no issues found in 73 source files`
- `corepack pnpm verify` runs format, lint, typecheck, both test suites, contracts check, and Next.js web build cleanly.

The database is at migration revision `20260827_0006_geocoding`, with 208,059 gazetteer places and 75 country aliases seeded.

---

## Current Pipeline State

```text
[GDELT 15m Poll]
       │
       ▼
[Gate 1: Negative-Only Filtering] (`discover_runner.py`)
       │  ↳ Rejections in `rejected_sightings`
       ▼
[Polite Web Retrieval] (`ArticleFetcher`)
       │  ↳ Stubs marked `processing_status = 'needs_review'`
       ▼
[Gate 2: Conservative Deduplication] (`dedupe_runner.py`)
       │  ↳ Syndicated copies marked `duplicate`
       │  ↳ Independent primary stories marked `normalized`
       ▼
[Gate 3: AI Classification & Grounded Extraction] (`extract_runner.py`)
       │  ↳ Batched relevance verdict -> `classified`
       │  ↳ Grounded extraction -> `extracted`, `signals.ai_extraction`, `disease_id`
       │  ↳ Cost audited in `ai_requests`
       ▼
[Sub-Project D1: Geocoding] (`geocode_runner.py`)
       │  ↳ Extracted places resolved against GeoNames gazetteer
       │  ↳ `signal_locations` rows with PostGIS geometry & precision
       │  ↳ Ambiguity coarsens to centroid, never tie-breaks
       │  ↳ Marked `processing_status = 'geocoded'`
       ▼
[Sub-Project D2: Story Clustering, Event Matching, Dual Scoring] <--- (YOU ARE HERE)
       │  ↳ Signals clustered into stories
       │  ↳ Clusters matched to `events` or creating new events -> `matched`
       │  ↳ `early_signal_score` and `evidence_score` calculated
       │  ↳ Observations recorded in `event_observations`
       ▼
[Sub-Project E: Signal Radar API & UI]
```

---

## What Sub-Project D2 Inherits and Must Reconcile

1. **Spatial Input:** `signal_locations` is D2's spatial input. It carries `location_role`, `precision` (`place`, `admin2`, `admin1`, `country`, `unresolved`), coordinates (`latitude`, `longitude`), PostGIS `geometry` point (SRID 4326), `geocoding_confidence`, and `geocoding_source`.
2. **Precision Weighting:** The gazetteer holds no place below ~1,000 inhabitants. Small settlements coarsen to district (`admin2`), province (`admin1`), or country centroids. D2 must account for location precision: a `country`-precision location should carry far lower spatial clustering weight than a `place`-precision location.
3. **Score Reconcilement:** The foundation migration created `events.attention_score` and `events.confidence_score`. `CONTEXT.md` specifies **`early_signal_score`** and **`evidence_score`**. D2 must explicitly reconcile or migrate these columns to match domain definitions.
4. **Events Table Writer:** D2 is the first and only writer of the event tables (`events`, `event_signals`, `event_observations`, `event_locations`).
5. **No Grounded Location Spans:** As established in Sub-project C and D1, `signals.ai_extraction["locations"]` carries extracted names without `source_span`s. D2 consumes `signal_locations` as-is.

---

## Known Follow-Ups Carried Forward

From Sub-project C's review:
- `ai_request_delay_seconds` is declared in `config.py`, but pacing is handled per batch rather than between individual requests.
- `DEFAULT_MIN_CONFIDENCE` in `ai/extract.py` is `0.50`, while `extract_runner.py` passes `settings.ai_min_confidence` (`0.60`).
- `SqlAlchemyAiRepository.record_extraction` updates `summary` and `signal_type` alongside `ai_extraction` and `disease_id`.
- `ladder.climb()` records `latency_ms = 0` on `ModelUnavailable` where no round trip occurred.

---

## Invariants for Sub-Project D2

1. **Conservative Event Matching:** When in doubt, keep events separate rather than erroneously merging distinct outbreaks. Merging distinct outbreaks corrupts historical traceability.
2. **Never Overwrite Observation History:** New figures arrive as new rows in `event_observations`, preserving the signal that reported them and the time they were seen. Never update past case counts in place.
3. **Keep the Two Scores Separate:** `early_signal_score` and `evidence_score` answer different questions (urgency vs. verification). Never blend them into a single vanity index.
4. **Official Source Weighting:** Official health authority reports (WHO, ECDC, CDC) increase `evidence_score` and set `verification_status` to `officially_confirmed`. Informal media signals drive `early_signal_score`.
5. **Seam Discipline:** Keep clustering and scoring decision logic pure (zero database driver or network imports in decision modules). All database interaction belongs in repository adapters.
