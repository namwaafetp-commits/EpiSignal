# Handoff — Sub-Project D: Story Clustering, Event Matching, and Dual Scoring

**Date:** 2026-08-27
**Branch:** `main` (clean, 497 passing tests)
**Head:** `0172a5c` — Sub-project C merged; `verify` script repaired
**State:** Sub-projects A, B, and C are complete, verified, and merged. **Sub-project
D has no design document and no implementation plan yet.** The design cycle is the
first piece of work, not the implementation.

---

## Start Here

Read in this exact order:

1. This file (`HANDOFF.md`);
2. `AGENTS.md` — model routing, project skills, TDD rules, token efficiency, provenance principles;
3. `CONTEXT.md` — the naming authority. Use signal, primary, event, observation, location role, early signal score, evidence score, and verification status exactly as defined there;
4. `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md` — the umbrella architecture and its invariants;
5. `docs/superpowers/specs/2026-08-27-ai-extraction-design.md` — Sub-project C's design, whose "Out of scope" section names what D inherits;
6. `docs/reports/2026-08-27-subproject-c-report.md` — Sub-project C's completion report, including its two-axis review findings;
7. `report.md` — the completion ledger for Sub-project B.

There is no Sub-project D design document or plan to read, because none has been
written. Produce them before writing code, in the same cycle A, B, and C each
followed: brainstorm the scope, write the design under
`docs/superpowers/specs/`, get it approved, write the task plan under
`docs/superpowers/plans/`, then execute it one red-green cycle and one commit at
a time.

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
[Sub-Project D: Geocoding, Clustering, Event Matching, Dual Scoring] <--- (YOU ARE HERE, nothing built yet)
       │  ↳ Extracted place names resolved to coordinates (`processing_status = 'geocoded'`)
       │  ↳ Signals grouped into story clusters
       │  ↳ Clusters matched to an existing event or creating a new one (`processing_status = 'matched'`)
       │  ↳ `early_signal_score` and `evidence_score` computed separately
       ▼
[Sub-Project E: Signal Radar API, Signal Radar UI, admin monitoring]
```

---

## What Sub-Project D Inherits

**The event schema already exists.** The foundation migration created `events`,
`event_signals`, `event_observations`, and `event_locations`, along with the
`EventStatus`, `RelationshipType`, `LocationRole`, and `VerificationStatus`
vocabularies. **No pipeline has ever written a row to any of them.** The WHO DON
and ECDC connectors produce signals, not events, so every source in the system
currently stops at `extracted`. D is the sub-project that first fills the event
tables, for official and discovered sources alike, so its design decides how, not
whether, these tables are used.

**`ProcessingStatus` already reserves D's states.** `geocoded` and `matched` are
declared in `db/types.py` and are so far unreachable. D makes them reachable.

**`events.attention_score` and `events.confidence_score` already exist, and are
not the two scores D must compute.** `CONTEXT.md` names the two scores
`early_signal_score` and `evidence_score`, and the umbrella architecture forbids
merging them. Reconciling the two existing event columns with the two named
scores is a design decision D has to make explicitly, not a detail to settle
while coding.

**Extractions carry ungeocoded place names.** Sub-project C stores locations in
`signals.ai_extraction` as text with source spans. Nothing has resolved them to
coordinates, and no geocoding provider has been chosen.

---

## Invariants You Must Never Break

The umbrella architecture's invariants all still hold. These are the ones D is
most likely to breach:

1. **Conservative matching.** Falsely merging two events is worse than carrying a
   temporary duplicate. Matching weights and thresholds stay configurable, and the
   ambiguous band escalates for review rather than guessing.
2. **Two scores, never merged.** `early_signal_score` answers how interesting a
   signal is; `evidence_score` answers how strongly it is supported. A local
   newspaper report can be 92 and 38 at once.
3. **Confirmation is earned, not inferred.** A GDELT-only event begins at
   `monitoring`. `officially_confirmed` requires an official source, and no model
   confidence value can grant it.
4. **An event's history is its observations.** Write a new `event_observations`
   row; never overwrite a running total on the event.
5. **A number without its span is never stored.** Observations promoted out of
   `signals.ai_extraction` keep their grounding.
6. **Official source provenance is only added to.** The WHO DON and ECDC
   connectors write `signals`, not events, and their signals flow through the same
   `fetched` → `normalized` → `classified` → `extracted` states as GDELT ones. D
   must not weaken the official columns or the source standing those signals
   carry when it starts grouping them.
7. **Decision modules import neither SQLAlchemy nor httpx.** Sub-project C's seam
   discipline is the house pattern: pure decision modules, one repository module
   for the database, one adapter module per network provider.
8. **Absence is `None`, never `False` and never `0`.**

---

## Known Follow-Ups Carried Forward

From Sub-project C's two-axis review. None is blocking, and each is worth a
decision during D's design:

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

Any live pass needs `apps/api/.env` populated and a reachable PostgreSQL with
PostGIS. `EPISIGNAL_OPENROUTER_API_KEY` is already required by the extraction
pass. Sub-project D will add at least one geocoding provider, whose key and rate
limits belong in the same file and whose free-tier terms should be confirmed
during design rather than during implementation.

Everything except the final live-verification task must run with no key, no
socket, and no database.

---

## Definition of Done

Sub-project D's own plan will carry its acceptance criteria. The project gates do
not change:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src packages/backend/src
corepack pnpm verify
```

Then use the `code-review` skill against the base commit, then `verify-and-stop`,
then write the completion report into `docs/reports/` in the shape Sub-project C's
entry uses.
