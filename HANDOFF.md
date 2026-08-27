# Handoff — Sub-Project D1: Geocoding Extracted Places

**Date:** 2026-08-27
**Branch:** `main` (clean, 497 passing tests)
**Head:** `6399616` — Sub-project D1 designed and planned; no D1 code exists yet
**State:** Sub-projects A, B, and C are complete, verified, and merged. Sub-project
D has been split in two. **D1 (geocoding) is designed, approved, and planned; your
job is to execute the plan.** D2 (story clustering, event matching, dual scoring)
is not yet designed and comes after D1.

## Why D was split

The umbrella architecture scopes Sub-project D as four subsystems: geocoding,
story clustering, event matching, and dual scoring. Sub-project C was twenty-one
tasks for one subsystem, so all four in one cycle would have produced a spec
roughly double the largest that has worked in this repository.

Geocoding is split out first because it has its own reference data and its own
failure modes, depends on nothing clustering decides, and produces the
coordinates clustering consumes. Building both together would have meant
designing the consumer before the producer existed.

---

## Start Here

Read in this exact order:

1. This file (`HANDOFF.md`);
2. `AGENTS.md` — model routing, project skills, TDD rules, token efficiency, provenance principles;
3. `CONTEXT.md` — the naming authority. Use signal, primary, event, observation, location role, early signal score, evidence score, and verification status exactly as defined there;
4. `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md` — the umbrella architecture and its invariants;
5. `docs/superpowers/specs/2026-08-27-geocoding-design.md` — **the approved design for this sub-project**;
6. `docs/superpowers/plans/2026-08-27-geocoding.md` — **the 21-task implementation plan you are executing**;
7. `docs/superpowers/specs/2026-08-27-ai-extraction-design.md` — Sub-project C's design, whose "Out of scope" section names what D inherits;
8. `docs/reports/2026-08-27-subproject-c-report.md` — Sub-project C's completion report, including its two-axis review findings;
9. `report.md` — the completion ledger for Sub-project B.

Then begin at Task 1 of the plan. Do the tasks in order. Each is one red-green
cycle and one commit, and each task's failing test depends only on files that
task or an earlier task creates.

Tasks 1 through 20 run with no key, no socket, and no database. Task 21 is the
only one that downloads anything or touches PostgreSQL.

---

## Windows Environment Facts

- **Python:** Run all commands through `uv run`. Do not activate virtual environments manually. Bare `python` is not on `PATH`; use `uv run python`.
- **Node / pnpm:** `pnpm` is not on `PATH`, but `corepack` ships with Node and is. Always enter the workspace through `corepack pnpm <command>` (for example `corepack pnpm verify`, `corepack pnpm db:migrate`, `corepack pnpm extract:signals`). Composite scripts in the root `package.json` invoke their own sub-steps through `corepack` for the same reason; keep it that way when adding scripts.
- **PowerShell:** Commands run under Windows PowerShell 5.1 (no `&&`, no ternary, no `??`). Chain with `;`.
- **UTF-8 BOM:** When generating files via PowerShell scripts, strip the UTF-8 BOM or use standard python writers.

---

## Verified Baseline

Verify the baseline before beginning any new work:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src packages/backend/src
corepack pnpm verify
```

**Expected baseline output:**
- `497 passed, 1 warning`
- `All checks passed!`
- `119 files already formatted`
- `Success: no issues found in 64 source files`
- `corepack pnpm verify` runs format, lint, typecheck, both test suites, the contracts diff, and the Next.js build, and exits 0

The database is at migration revision `20260827_0005_ai_extraction`, with the
three-tier free AI model roster seeded.

---

## Current Architecture and Pipeline State

```text
[GDELT 15m Poll]
       │
       ▼
[Gate 1: Negative-Only Title & Domain Filtering] (run_discovery)
       │  ↳ Rejections recorded in `rejected_sightings` (costs 0 page fetches)
       ▼
[Polite Web Retrieval] (ArticleFetcher with robots.txt compliance & rate limiting)
       │  ↳ Failures stored as stubs (`processing_status = 'needs_review'`)
       ▼
[Gate 2: Conservative Deduplication] (corepack pnpm dedupe:signals)
       │  ↳ Syndicated copies linked via `duplicate_of_signal_id` (`processing_status = 'duplicate'`)
       │  ↳ Independent primary stories marked (`processing_status = 'normalized'`)
       ▼
[Gate 3: AI Classification & Grounded Extraction] (corepack pnpm extract:signals)
       │  ↳ Batched relevance verdict (`processing_status = 'classified'`)
       │  ↳ Grounded extraction (`processing_status = 'extracted'`, `signals.ai_extraction`, `signals.disease_id`)
       │  ↳ Every request costed in `ai_requests`
       ▼
[Sub-Project D1: Geocoding] <--- (YOU ARE HERE, designed and planned, nothing built yet)
       │  ↳ Extracted place names resolved against a seeded GeoNames gazetteer
       │  ↳ One `signal_locations` row per named place, carrying its precision
       │  ↳ Ambiguity coarsens to an admin1 or country centroid, never tie-breaks
       │  ↳ (`processing_status = 'geocoded'`)
       ▼
[Sub-Project D2: Story Clustering, Event Matching, Dual Scoring] (not yet designed)
       │  ↳ Signals grouped into story clusters
       │  ↳ Clusters matched to an existing event or creating a new one (`processing_status = 'matched'`)
       │  ↳ `early_signal_score` and `evidence_score` computed separately
       ▼
[Sub-Project E: Signal Radar API, Signal Radar UI, admin monitoring]
```

---

## What Sub-Project D1 Inherits

**Extractions carry ungeocoded place names, and they are not grounded.**
Sub-project C stores locations in `signals.ai_extraction` as `role`, `country`,
`admin1`, and `place_name`. Unlike every stored count, an `ExtractedLocation`
carries **no `source_span`**, so places are the one extracted fact that was never
checked against the article. D1 does not reopen that; it records the extraction's
own strings verbatim beside its resolution. Closing the gap needs a schema change
in Sub-project C and re-extraction of every signal already processed, which is
why the design writes it down rather than doing it.

**`ProcessingStatus` already reserves the state.** `geocoded` is declared in
`db/types.py` and is so far unreachable. D1 makes it reachable. `matched` stays
unreachable until D2.

**Nothing writes events, and D1 still will not.** The foundation migration
created `events`, `event_signals`, `event_observations`, and `event_locations`,
and no pipeline has ever written a row to any of them — the WHO DON and ECDC
connectors produce signals, not events. D1 writes only its own
`signal_locations` table. D2 is what first fills the event tables.

**A decision D2 inherits, not D1.** `events.attention_score` and
`events.confidence_score` already exist and are *not* the two scores `CONTEXT.md`
names. Reconciling them with `early_signal_score` and `evidence_score` is a D2
design decision, to be made explicitly rather than settled while coding.

---

## Invariants You Must Never Break

The umbrella architecture's invariants all still hold. These are the ones D1 is
most likely to breach:

1. **Ambiguity coarsens; it never tie-breaks.** Two plausible candidates yield
   the province centroid, not the more populous candidate. A province centroid is
   a less precise true statement; the biggest Springfield is a guess wearing a
   coordinate. `Candidate` deliberately does not carry population, so the ladder
   structurally cannot consult it.
2. **Placing an outbreak in the wrong country is the worst available error.**
   Country names resolve by exact match against a reviewed alias list, never
   fuzzily. Niger silently becoming Nigeria is the failure this rule prevents.
3. **Precision is recorded on every row.** A province centroid and a town centre
   are both coordinates, and only the stored precision tells them apart. D2 must
   be able to weigh them differently.
4. **Absence is `None`, never `False` and never `0`.** An unresolved location
   carries null latitude, longitude, geometry, and confidence. A zero confidence
   would claim an assessment that was never made.
5. **Nothing here writes events, `verification_status`, `diseases`, or
   `pathogens`,** and nothing modifies `signals.ai_extraction`. The extraction is
   the model's answer; D1 records its own answer beside it.
6. **"Could not resolve" is not "failed".** A signal whose places all fail to
   resolve still advances to `geocoded`. No signal reaches `needs_review` through
   this pass.
7. **Decision modules import neither SQLAlchemy nor httpx.** Sub-project C's seam
   discipline is the house pattern: pure decision modules, one repository module
   for the database, one adapter module per network provider. D1 has no network
   adapter at all, and a test enforces that.
8. **Official source provenance is only added to.** The WHO DON and ECDC
   connectors write `signals`, not events, and their signals flow through the same
   `fetched` → `normalized` → `classified` → `extracted` states as GDELT ones.

These remain in force for D2 and are not D1's to satisfy: conservative event
matching, the two unmerged scores, confirmation earned rather than inferred, and
an event's history being its observations rather than an overwritten total.

---

## Known Follow-Ups Carried Forward

From Sub-project C's two-axis review. None is blocking, and none is D1's to fix:

- `ai_request_delay_seconds` is declared in `config.py`, but pacing happens per
  request batch rather than between individual requests.
- `DEFAULT_MIN_CONFIDENCE` in `ai/extract.py` is `0.50`, while `extract_runner.py`
  passes `settings.ai_min_confidence` (`0.60`). The constant is dead in practice
  and misleading in isolation.
- `SqlAlchemyAiRepository.record_extraction` writes `summary` and `signal_type`
  alongside `ai_extraction` and `disease_id`, which is wider than its name implies.
- `ladder.climb()` records `latency_ms = 0` on `ModelUnavailable`, where no round
  trip was ever timed. A null would say what happened; a zero says something false.
- Two stale git worktrees exist. `.worktrees/ingestion` holds
  `feat/who-don-ingestion`, which is merged into `main` and can be pruned.
  `C:/Users/DELL/.codex/worktrees/f11d/EpiSignal` holds `feat/ai-extraction`,
  which is **not** merged: it carries six documentation-only commits containing an
  earlier draft of the Sub-project C design and plan that `main` superseded.
  Confirm nothing on it is still wanted before removing either.

---

## Before You Can Run It Live

Task 21 is the only task that touches the network or a database. It needs:

- `apps/api/.env` populated, and a reachable PostgreSQL with PostGIS;
- the four GeoNames files downloaded from
  `https://download.geonames.org/export/dump/` — `countryInfo.txt`,
  `admin1CodesASCII.txt`, `admin2Codes.txt`, and `cities1000.zip`. Not
  `allCountries.txt`: it is 12 million rows and the wrong input;
- at least one signal at `processing_status = 'extracted'` in the database.

**D1 adds no API key and no rate limit,** because it calls no provider. The
gazetteer is a committed seed artifact, so a clone can migrate, seed, and geocode
with no account and no socket. Adding a network geocoder later is an adapter
module and a precision rung, not a change to the resolution policy.

Everything before Task 21 runs with no key, no socket, and no database.

---

## Definition of Done

The design's thirteen acceptance criteria, each mapped to the test that verifies
it in the plan's closing Verification Checklist, plus the project gates:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src packages/backend/src
corepack pnpm verify
```

Then use the `code-review` skill against `2f01d31`, then `verify-and-stop`, then
write `docs/reports/2026-08-27-subproject-d1-report.md` in the shape Sub-project
C's entry uses, and rewrite this file to target D2. Task 21 Step 10 lists exactly
what the D2 handoff must carry forward.
