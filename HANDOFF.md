# Handoff — Sub-Project C: AI Classification, Extraction, and Cost Accounting

**Date:** 2026-08-27
**Branch:** `main` (clean, 357 passing tests)
**Head:** `e39ab9d` — design, plan, and `CONTEXT.md` committed
**State:** Sub-project B (Stage 0) is complete, verified, and merged. The Sub-project C **design is approved** and the implementation plan is written. **No Sub-project C code exists yet.** Your job is to execute the plan.

---

## Start Here

Read in this exact order:

1. This file (`HANDOFF.md`);
2. `AGENTS.md` — model routing, project skills, TDD rules, token efficiency, provenance principles;
3. `CONTEXT.md` — the naming authority. Use tier, escalation, source span, grounding, cost row, unavailable, and verdict exactly as defined there;
4. `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md` — the umbrella architecture and its invariants;
5. `docs/superpowers/specs/2026-08-27-ai-extraction-design.md` — **the approved design for this sub-project**;
6. `docs/superpowers/plans/2026-08-27-ai-extraction.md` — **the 21-task implementation plan you are executing**;
7. `report.md` — the completion ledger for Sub-project B.

Then begin at Task 1 of the plan. Do the tasks in order. Each is one red-green
cycle and one commit, and each task's failing test depends only on files that
task or an earlier task creates.

---

## Windows Environment Facts

- **Python:** Run all commands through `uv run`. Do not activate virtual environments manually.
- **Node / pnpm:** `pnpm` is not on `PATH`. Always use `corepack pnpm <command>` (e.g. `corepack pnpm verify`, `corepack pnpm db:migrate`, `corepack pnpm extract:signals`).
- **PowerShell:** Commands run under Windows PowerShell 5.1 (no `&&`, no ternary, no `??`).
- **UTF-8 BOM:** When generating files via PowerShell scripts, strip UTF-8 BOM (`\xef\xbb\xbf`) or use standard python writers.
- **Bare `python` is not on `PATH`.** Use `uv run python`.

---

## Verified Baseline

Verify the baseline before beginning any new work:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src packages/backend/src
```

**Expected Baseline Output:**
- `357 passed`
- `All checks passed!`
- `94 files already formatted`
- `Success: no issues found in 51 source files`

Note: this repository's pytest configuration suppresses the summary line. Count
the progress dots, or run a subset with `-v`, to confirm 357.

---

## Current Architecture & Pipeline State

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
[Gate 2: Conservative Deduplication] (pnpm dedupe:signals / run_dedupe)
       │  ↳ Syndicated copies linked via `duplicate_of_signal_id` (`processing_status = 'duplicate'`)
       │  ↳ Independent primary stories marked (`processing_status = 'normalized'`)
       ▼
[Sub-Project C: AI Classification & Extraction] <--- (YOU ARE HERE, nothing built yet)
       │  ↳ Batched relevance verdict (`processing_status = 'classified'`)
       │  ↳ Grounded extraction (`processing_status = 'extracted'`, `signals.ai_extraction`)
       │  ↳ Every request costed in `ai_requests`
       ▼
[Sub-Project D: Clustering, Event Matching, Dual Scoring]
```

---

## What Was Decided, and What It Changed

The design is approved as written. Four decisions differ from what the earlier
handoff sketched, and the plan already reflects all of them.

1. **Free OpenRouter endpoints only, on all three tiers.** No paid model is
   seeded and expected spend is 0.00 USD. This is stricter than the umbrella
   architecture's 0–5 USD per month budget, not in conflict with it. The price
   table, the cost computation, and the cost cap are all still built, so adding a
   paid rung later is a seed row and a key, never a code change.
2. **Requests are the scarce resource, not dollars.** Free endpoints are limited
   per minute and per day. `EPISIGNAL_AI_MAX_REQUESTS_PER_RUN` is the guard that
   actually binds; the cost cap guards a tier that does not exist yet.
3. **The model roster is a seeded table (`ai_models`), not configuration.** Free
   endpoints are withdrawn without notice, so replacing one must not require a
   deployment. The three seeded ids come from three different vendors on purpose:
   a ladder whose rungs share a family fails the same way on the same document.
4. **Every stored number carries a `source_span` that is checked against
   `raw_text`.** This is the spine of the whole sub-project. An extracted count
   whose span does not appear in the article is a fabrication, and the extraction
   is rejected whole rather than partially salvaged.

---

## Invariants You Must Never Break

1. **Signals with `duplicate`, `needs_review`, or `fetched` are never sent to AI.**
   Only `normalized` signals enter classification, and only `classified` signals
   with `public_health_relevant = true` enter extraction. The selection queries
   are the enforcement, and the plan tests them directly.
2. **AI confidence is not ground truth.** No model confidence value promotes a
   signal to `officially_confirmed`. Nothing in this sub-project writes
   `verification_status` at all.
3. **Cheap before expensive.** Deterministic checks run before model calls, and
   escalation happens only when a check rejects an answer.
4. **Official source provenance remains untouched.** WHO DON and ECDC pipelines
   operate independently; their models and observation records stay intact.
5. **A number without its span is never stored.** If a change would let an
   ungrounded number through, the change is wrong.
6. **"Could not ask" is not "asked and could not trust."** A rate limit, timeout,
   or exhausted guard leaves the signal exactly as it was, for the next run. Only
   a validated rejection at every tier sends it to `needs_review`.
7. **Decision modules import neither SQLAlchemy nor httpx.** Only
   `ai/repository.py` imports SQLAlchemy; only `ai/openrouter.py` imports httpx.
8. **Absence is `None`, never `False` and never `0`.** An empty `transmission`
   object is not a finding.

---

## Before You Can Run It Live

Task 21 is the only task that touches the network or a database. It needs:

- `EPISIGNAL_OPENROUTER_API_KEY` set in `apps/api/.env`;
- the three seeded model ids in `database/seeds/ai_models.json` confirmed against
  the live OpenRouter model list — they were written on 2026-08-27 and free
  endpoints disappear without notice;
- at least one signal at `processing_status = 'normalized'` in the database.

Everything before Task 21 runs with no key, no socket, and no database.

---

## Definition of Done

The plan's own acceptance criteria, all fourteen of them, plus the project gates:

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src packages/backend/src
corepack pnpm verify
```

Then use the `code-review` skill against `e39ab9d`, then `verify-and-stop`, and
write the completion report into `report.md` in the shape Sub-project B's entry
uses.
