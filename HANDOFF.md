# Handoff — Sub-Project C: AI Classification, Extraction, and Cost Tracking

**Date:** 2026-08-27
**Branch:** `main` (clean, 357 passing tests)
**Base:** `main` (includes Sub-project A `feat/gdelt-discovery` and Sub-project B `feat/gdelt-stage0`)
**State:** Sub-project B (Stage 0 Deduplication and Rule Filtering) is complete, verified, and merged. Next up is **Sub-Project C** (AI: batched classification, extraction, escalation, and cost logging).

---

## Start Here

Read in this exact order:

1. This file (`HANDOFF.md`);
2. `AGENTS.md` — model routing, TDD rules, token efficiency, and provenance principles;
3. `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md` — the umbrella architecture defining sub-project boundaries (A through F);
4. `report.md` — the completion ledger and verification report for Sub-project B;
5. Requirements document (Section 31, Priority items 6–8, 23).

Then begin by drafting the **Design Specification** for Sub-Project C in `docs/superpowers/specs/2026-08-27-ai-extraction-design.md`, followed by the **Implementation Plan** in `docs/superpowers/plans/2026-08-27-ai-extraction.md`.

---

## Windows Environment Facts

- **Python:** Run all commands through `uv run`. Do not activate virtual environments manually.
- **Node / pnpm:** `pnpm` is not on `PATH`. Always use `corepack pnpm <command>` (e.g. `corepack pnpm verify`, `corepack pnpm dedupe:signals`, `corepack pnpm db:migrate`).
- **PowerShell:** Commands run under Windows PowerShell 5.1 (no `&&`, no ternary, no `??`).
- **UTF-8 BOM:** When generating files via PowerShell scripts, strip UTF-8 BOM (`\xef\xbb\xbf`) or use standard python writers.

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
[Sub-Project C: AI Classification & Extraction] <--- (YOU ARE HERE)
```

---

## What Sub-Project C Builds

Sub-project C processes signals with `processing_status = 'normalized'` through an intelligent, cost-bounded AI extraction pipeline:

1. **Batched Relevance Classification:**
   - Fast, low-latency relevance evaluation (outbreak vs. non-outbreak context).
   - Structured JSON response validation.

2. **Epidemiological Information Extraction:**
   - Extract disease entity (resolved or candidate string).
   - Extract syndromic and pathogen signals.
   - Extract quantitative metrics (suspected cases, confirmed cases, deaths, hospitalizations).
   - Extract spatio-temporal intervals (locations mentioned, event date, data-as-of date).

3. **Multi-Tier Model Escalation Hierarchy:**
   - **Tier 1 (Default, ~90-95%):** Free OpenRouter endpoints (e.g., Llama 3.3 70B, Gemini Flash Free).
   - **Tier 2 (Fallback / Ambiguous):** Low-cost paid model (e.g., Gemini 2.0 Flash).
   - **Tier 3 (Escalation / Complex Multilingual):** High-reasoning model for low-confidence or conflicting extractions.

4. **Token Usage & Cost Accounting:**
   - Audit logging table recording prompt tokens, completion tokens, model name, latency, and computed USD cost per call.

---

## Invariants You Must Never Break

1. **Signals with `duplicate` or `needs_review` are never sent to AI.** Only `normalized` signals enter the AI pipeline.
2. **AI Confidence is NOT Ground Truth.** Model confidence values must never automatically promote unverified media signals to `officially_confirmed`.
3. **Cheap before expensive.** Deterministic JSON schemas and prompt constraints run before model calls; escalation only triggers when Tier 1 fails or reports low extraction confidence.
4. **Official Source Provenance remains untouched.** WHO DON and ECDC pipelines operate independently; their models and observation records must remain intact.
