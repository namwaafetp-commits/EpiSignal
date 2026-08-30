# Handoff — Sub-Project D2a: Story Clustering, Event Matching, and Dual Scoring

**Date:** 2026-08-28
**Branch:** `main` (clean, 618 passing tests)
**Head:** Sub-project D1 complete and verified; `signal_locations` exists and is populated with PostGIS geometry and GIST indexing.
**State:** `P0`–`P3`, `A`, `B`, `C`, and `D1` are complete, verified, and merged. `D2a` is **designed and planned**. **Your task is to implement Sub-Project D2a, task by task, from the committed plan.**

---

## Scope note: D2 was split

The original `D2` covered clustering, matching, dual scoring, *and* embedding
similarity with LLM escalation. It is now two items:

- **`D2a` — this one.** Entirely deterministic. No model call, no socket, no
  embedding. Same input rows produce the same events every time.
- **`D2b` — later.** Embedding similarity and escalated model judgement for the
  ambiguous matches `D2a` deliberately refuses.

If you find yourself reaching for embeddings or a model call, you have crossed
into `D2b`. Stop and report instead.

---

## What Sub-Project D2a Builds

1. **Story Clustering:** Groups signals reporting the same outbreak by identical disease, a temporal window, and precision-governed spatial agreement.
2. **Event Matching & Creation:** Exactly one candidate above threshold attaches; none creates a new event; two or more refuses and routes to `needs_review`. Transitions signals to `processing_status = 'matched'`.
3. **Dual Scoring Engine:** Two independent deterministic weighted formulas, both on `0–1`, over stored fields with weights in configuration.
4. **Observation History Tracking:** One new `event_observations` row per newly attached signal. Never an update.

---

## Start Here

Read in this exact order:

1. This file (`HANDOFF.md`);
2. `STATUS.md` — the current position, the 22-task ledger, settled decisions, and the verified baseline;
3. `ROADMAP.md` — where `D2a` sits and what it unblocks;
4. `docs/agents/workflow.md` — the planner and worker contract and the completion gate;
5. `docs/superpowers/specs/2026-08-28-story-clustering-design.md` — the design you are implementing;
6. `docs/superpowers/plans/2026-08-28-story-clustering.md` — the 22 tasks, in order;
7. `AGENTS.md` — model routing, project skills, TDD rules, token efficiency, provenance principles;
8. `CONTEXT.md` — the naming authority. Use signal, primary, event, observation, location role, early signal score, evidence score, and verification status exactly as defined there;
9. `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md` — the umbrella architecture and its invariants;
10. `docs/reports/2026-08-27-subproject-d1-report.md` — Sub-project D1's completion report.

When `D2a` reaches `verified`, archive this file to `docs/handoffs/2026-08-28-d2a.md`
before rewriting it for the next item. Do not overwrite it in place.

---

## Windows Environment Facts

- **Python:** Run all commands through `uv run`. Do not activate virtual environments manually. Bare `python` is not on `PATH`; use `uv run python`.
- **Node / pnpm:** `pnpm` is not on `PATH`, but `corepack` ships with Node and is. Always enter the workspace through `corepack pnpm <command>` (for example `corepack pnpm verify`, `corepack pnpm db:migrate`, `corepack pnpm match:events`).
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
- `corepack pnpm verify` runs format, lint, typecheck, both test suites, contracts check, and Next.js build cleanly.

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
[Sub-Project D2a: Clustering, Matching, Dual Scoring] (`event_runner.py`) <--- (YOU ARE HERE)
       │  ↳ Signals clustered into story clusters
       │  ↳ Clusters matched to `events` or creating new events -> `matched`
       │  ↳ Ambiguous clusters refused -> `needs_review`
       │  ↳ `early_signal_score` and `evidence_score` calculated, both 0–1
       │  ↳ Observations recorded in `event_observations`
       ▼
[Sub-Project D2b: Embedding similarity and LLM escalation]
       ▼
[Sub-Project E: Signal Radar API & UI]
```

---

## What Sub-Project D2a Inherits and Must Reconcile

1. **Spatial Input:** `signal_locations` is D2a's spatial input. It carries `location_role`, `precision` (`place`, `admin2`, `admin1`, `country`, `unresolved`), coordinates (`latitude`, `longitude`), PostGIS point (SRID 4326), `geocoding_confidence`, and `geocoding_source`.
2. **Precision Weighting:** The gazetteer holds no place below ~1,000 inhabitants. Small settlements coarsen to district (`admin2`), province (`admin1`), or country centroids. A `country`-precision location carries far lower weight than a `place`-precision one, and **must never be compared to a town by distance**.
3. **Score Reconcilement — settled.** Task 12 renames `events.attention_score` to `early_signal_score` and `events.confidence_score` to `evidence_score`, widening both check constraints to `0–1`. The table is empty, so nothing moves. Do not shadow the old names in a mapping layer.
4. **Geography, not Geometry.** `point_4326()` in `models/event.py` returns a **Geography** type, so PostGIS distances are already in metres. Do not convert.
5. **Events Table Writer:** D2a is the first and only writer of the event tables (`events`, `event_signals`, `event_observations`, `event_locations`).
6. **No Grounded Location Spans:** As established in Sub-project C and D1, `signals.ai_extraction["locations"]` carries extracted names without `source_span`s. D2a consumes `signal_locations` as-is.
7. **`ProcessingStatus.MATCHED` already exists** in `db/types.py`. Do not add it.

---

## Known Follow-Ups Carried Forward

From Sub-project C's review:
- `ai_request_delay_seconds` is declared in `config.py`, but pacing is handled per batch rather than between individual requests.
- `DEFAULT_MIN_CONFIDENCE` in `ai/extract.py` is `0.50`, while `extract_runner.py` passes `settings.ai_min_confidence` (`0.60`).
- `SqlAlchemyAiRepository.record_extraction` updates `summary` and `signal_type` alongside `ai_extraction` and `disease_id`.
- `ladder.climb()` records `latency_ms = 0` on `ModelUnavailable` where no round trip occurred.

None of these block D2a. Do not fix them inside D2a; note them forward.

---

## Invariants for Sub-Project D2a

1. **Conservative Event Matching:** When in doubt, keep events separate rather than erroneously merging distinct outbreaks. Merging distinct outbreaks corrupts historical traceability. Two candidates above threshold means refuse, not pick the higher one.
2. **Never Overwrite Observation History:** New figures arrive as new rows in `event_observations`, preserving the signal that reported them and the time they were seen. Never update past case counts in place. An absent count is stored as null, never as zero.
3. **Keep the Two Scores Separate:** `early_signal_score` and `evidence_score` answer different questions (urgency vs. verification). Never blend them into a single vanity index, and never let one read the other.
4. **Official Source Weighting:** Official health authority reports (WHO, ECDC, CDC) increase `evidence_score` and set `verification_status` to `officially_confirmed`. Informal media signals drive `early_signal_score`. No model confidence can raise a verification status.
5. **Seam Discipline:** Keep clustering, matching, and scoring logic pure (zero database driver or network imports in decision modules). All database interaction belongs in `events/repository.py`. A seam test enforces this, as it does for D1.
6. **Determinism:** D2a makes no model call and opens no socket. Same rows in, same events out.
