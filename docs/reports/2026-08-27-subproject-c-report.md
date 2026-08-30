# Sub-Project C Completion Report: AI Classification, Extraction, and Cost Accounting

**Date:** 2026-08-27  
**Repository:** `EpiSignal` (`namwaafetp-commits/EpiSignal`)  
**Base Commit:** `109da37`  
**Head Commit:** `fc97f56`  

---

## 1. Executive Summary

Sub-Project C of EpiSignal introduces a multi-tier AI classification and extraction pipeline with grounded provenance verification and exact cost ledger accounting. All 21 tasks specified in `docs/superpowers/plans/2026-08-27-ai-extraction.md` have been implemented, tested test-first via strict TDD red-green cycles, and verified against the full quality gate.

Key guarantees enforced across the pipeline:
1. **Purity of Seams:** Decision modules (`schema.py`, `validate.py`, `ladder.py`, `prompts.py`, `classify.py`, `extract.py`) contain 0 imports of SQLAlchemy or httpx. Only `ai/repository.py` touches the database, and only `ai/openrouter.py` makes network requests.
2. **Grounding & Provenance:** Every epidemiological metric (`confirmed_cases`, `total_cases`, `deaths`, `new_cases`, etc.) and transmission flag requires a verbatim `source_span` present in the original `raw_text`. Any ungrounded metric rejects the extraction and escalates.
3. **Audit Ledger Protection:** All AI invocations record token counts, latency, and cost calculations in `ai_requests`. Migration `20260827_0005_ai_extraction` enforces non-destructive downgrade protections unless `EPISIGNAL_ALLOW_AI_AUDIT_LOSS=1` is explicitly set.
4. **State Machine Integrity:** Only `normalized` signals enter classification; only `classified` signals with `public_health_relevant=True` enter extraction. Signals with unavailable providers remain unmodified for future runs; only repeated validated rejections transition signals to `needs_review`.

---

## 2. Completed Tasks Summary

| Task | Commit | Description |
|:---|:---|:---|
| 1 | `ac601aa` | AI request purpose and outcome vocabulary (`AiPurpose`, `AiOutcome`) |
| 2 | `e79329f` | Strict epidemiological extraction schema (`Extraction`, `extraction_json_schema`) |
| 3 | `2e4df44` | Batched classification response schema (`ClassificationResponse`) |
| 4 | `61480e2` | Contracts for model and storage seams (`ModelSpec`, `Verdict`, etc.) |
| 5 | `12b9111` | Protocols for model and storage boundaries (`ChatModel`, `AiRepository`) |
| 6 | `3f528b9` | Structural validation and arithmetic consistency (`parse_extraction`, `check_arithmetic`) |
| 7 | `04eafd8` | Grounding, source span verification, and privacy redaction checks |
| 8 | `f3686c5` | Batch response identity and completeness validation (`validate_classification`) |
| 9 | `8cd52d3` | Model ladder, run guards, and per-million token cost arithmetic |
| 10 | `080659a` | System and user prompt builders (`classification_prompt`, `extraction_prompt`) |
| 11 | `d4540b1` | SQLAlchemy models for `AiModel`, `AiRequest`, and `Signal.disease_id` |
| 12 | `184cf4b` | Alembic migration `20260827_0005_ai_extraction` with ledger downgrade guards |
| 13 | `6afb8a8` | Seed data for 3-tier free AI model roster and seed upsert loader |
| 14 | `400eeb7` | `SqlAlchemyAiRepository` storage adapter meeting `AiRepository` boundary |
| 15 | `652ad02` | Ladder escalation climb and shared cost row record builder |
| 16 | `ade60e1` | Batched classification pass runner (`run_classification`) |
| 17 | `09210bf` | Single-signal grounded extraction pass runner (`run_extraction`) |
| 18 | `b8d0852` | `OpenRouterChatModel` client with bounded retries and error isolation |
| 19 | `898f9dc` | Configuration settings and environment validation for AI passes |
| 20 | `f3c594f` | CLI runner `extract_runner.py` and `pnpm extract:signals` script |
| 21 | `fc97f56` | Live roster sync, migration rollback verification, and full gate checks |

---

## 3. Active Free Model Roster (Verified against OpenRouter)

The free model roster was checked against OpenRouter's live API endpoints during Task 21:
- **Tier 1:** `google/gemma-4-31b-it:free` (Gemma 4 31B IT)
- **Tier 2:** `minimax/minimax-m2.7:free` (MiniMax M2.7)
- **Tier 3:** `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` (NVIDIA Nemotron 3 Nano Omni 30B Reasoning)

Database seeded successfully with 3 active tiers and `0.000000` cost per million tokens.

---

## 4. Verification and Quality Gates

All acceptance gates ran and passed:

1. **Python Unit & Integration Test Suite (`uv run pytest`):**
   - **Result:** `497 passed, 1 warning in 24.42s`
   - **Isolation:** 0 tests open sockets, read external credentials, or connect to live databases.
2. **Linting & Code Style (`uv run ruff check .`):**
   - **Result:** `All checks passed!`
3. **Code Formatting (`uv run ruff format --check .`):**
   - **Result:** `119 files already formatted`
4. **Static Type Checking (`uv run mypy apps/api/src packages/backend/src`):**
   - **Result:** `Success: no issues found in 64 source files`
5. **Web & Monorepo Verification:**
   - **Prettier:** `corepack pnpm --filter @episignal/web exec prettier --check .` -> PASS
   - **Web Lint:** `corepack pnpm --filter @episignal/web lint` -> PASS
   - **Web Typecheck:** `corepack pnpm --filter @episignal/web typecheck` -> PASS
   - **Web Tests:** `corepack pnpm --filter @episignal/web test` -> 10 passed (10)
   - **Web Build:** `corepack pnpm --filter @episignal/web build` -> Next.js production build succeeded
   - **API Contracts:** `openapi-typescript openapi.json` -> Schema diff clean

---

## 5. Two-Axis Code Review Summary (`109da37...HEAD`)

### Standards Axis
- **Hard Violations:** 0.
- **Architectural Conformance:** Strict isolation of decision modules from I/O; conservative event matching preserved; redaction checks in place; ledger accounting exact.
- **Baseline Smells (Judgement Calls):** 
  - Duplicated request builder closure pattern in `classify.py` and `extract.py`.
  - Parallel lifecycle structure between classification and extraction passes.

### Spec Axis
- **Missing / Partial Requirements:**
  - `ai_request_delay_seconds` setting is declared in `config.py` but pacing is handled per request batch rather than inter-request sleeping.
  - `DEFAULT_MIN_CONFIDENCE` constant in `extract.py` defaulted to `0.50` rather than `0.60`, though `extract_runner.py` explicitly supplies `settings.ai_min_confidence` (`0.60`).
- **Scope Creep / Inconsistencies:**
  - `SqlAlchemyAiRepository.record_extraction` updates `summary` and `signal_type` columns alongside `ai_extraction` and `disease_id`.
  - `climb()` sets `latency_ms=0` on `ModelUnavailable` exceptions when no round-trip timing was completed.

---

## 6. Conclusion

Sub-Project C is complete and ready for integration into downstream geocoding, clustering, and event matching (Sub-Project D).
