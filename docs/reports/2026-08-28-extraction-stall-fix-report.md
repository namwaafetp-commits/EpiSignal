# EpiSignal Report: Resolution of Extraction Pipeline Stall

**Date:** 2026-08-28
**Branch:** `fix/extraction-structured-outputs`
**Commit:** `117d0c8`
**Verification Gate:** `corepack pnpm verify` (exit code 0)

---

## 1. Executive Summary

This work resolves the complete extraction stage stall that was starving all downstream pipeline stages (geocoding, matching, clustering). Previously, 0% of extraction attempts were succeeding on the primary escalation target, with 36 out of 71 total historical AI requests rejected on `shape` due to OpenRouter sending only syntax-level `response_format: {"type": "json_object"}` without the schema contract.

With this change:
1. **Structured Outputs Enforced:** Extraction now sends OpenRouter structured outputs (`response_format: {"type": "json_schema", "json_schema": {"name": "extraction_response", "strict": true, "schema": ...}}`) generated dynamically from the Pydantic `Extraction` model (`Extraction.model_json_schema()`), eliminating schema drift. An explicit low temperature (`0.0`) is configured for deterministic extraction.
2. **Capability Detection & Dynamic Fallback:** Model support for structured outputs is detected statically, with dynamic runtime fallback to `json_object` if a provider returns HTTP 400.
3. **Evidence-Backed Model Ladder:** Refreshed the active model roster:
   - **Tier 1:** `deepseek/deepseek-chat` (DeepSeek V3, $0.26 / $1.03 per million) — promoted to Tier 1 as highest empirical performer.
   - **Tier 2:** `mistralai/mistral-small-24b-instruct-2501` (Mistral Small 24B, $0.05 / $0.08 per million) — high-speed, cost-effective structured output fallback.
   - **Tier 3:** `anthropic/claude-haiku-4.5` (Claude Haiku 4.5, $1.00 / $5.00 per million) — replaces obsolete `anthropic/claude-3-haiku` (which did not support structured outputs and scored 0/7).
4. **Auditable Backlog Requeue:** Implemented `requeue_extraction_backlog` which safely requeued 19 extraction-failed signals from `needs_review` to `CLASSIFIED`, while strictly preserving quarantined signal `852aa204-846d-4aa6-a256-82c187fdeaef` and invalid hash/discovery stubs.
5. **Live End-to-End Proof:** Re-driving the pipeline extracted 28 signals in a single pass with **zero shape rejections**, geocoded 32 signals, and created the first **3 real outbreak events** in the database.

---

## 2. Before / After Acceptance Measurements

### Historical Baseline (Before Fix)
Across 71 extraction requests in `ai_requests`:
- **Accepted:** 5 (7.0%)
- **Rejections:** 36 `shape`, 7 `ungrounded`, 2 `arithmetic`, 4 `not_json`
- **Failures:** 10 unavailable (`429`), 5 `no choices`
- **Tier 3 Escalation Target (`anthropic/claude-3-haiku`):** 0 for 7 (6 shape failures, 1 arithmetic)
- **Downstream Impact:** 0 geocoded signals, 0 events created, 27 signals stuck in `needs_review`.

### Live Measurements (After Fix)
- **Extraction Pass Output:** `extract ok classified=15 relevant=9 irrelevant=6 extracted=28 review=0 unavailable=0 requests=40`
- **Shape Rejections with Structured Outputs:** **0** (down from 36)
- **Signals Reaching `extracted`:** 32
- **Signals Reaching `geocoded`:** 32 (located 43 places across 62 coordinates)
- **Signals Reaching `matched` & Events Created:** 3 events created from 3 story clusters:
  1. `EVT-EEA92838`: Outbreak event in Geel, Belgium (early score: 0.462, evidence score: 0.352)
  2. `EVT-1BAC05A1`: Outbreak event in Nigeria (early score: 0.423, evidence score: 0.352)
  3. `EVT-F00791B8`: Outbreak event in Angola (early score: 0.276, evidence score: 0.852)

---

## 3. Backlog Requeue & Needs Review Distinction

`requeue_extraction_backlog` cleanly isolates extraction-exhausted signals from all other causes of `needs_review`:
- **Legitimate Extraction Failures Requeued (19 signals):** `processing_status == NEEDS_REVIEW`, `public_health_relevant is True`, non-empty `raw_text`, truthful `content_hash`, has prior `AiPurpose.EXTRACTION` attempts, and `ai_extraction is None`.
- **Quarantined Row Preserved (1 signal):** `852aa204-846d-4aa6-a256-82c187fdeaef` (Pennsylvania title / Luanda body / corrupt hash) strictly skipped and filtered.
- **Discovery Stubs Preserved (5 signals):** Missing `raw_text` / paywalled documents from ingestion.
- **Invalid Hash / Test Stubs Preserved (2 signals):** Hash mismatch rows skipped.

### Recommendation for Future Recording
Currently, `processing_status` is an enum (`NEEDS_REVIEW`) without an accompanying reason code column on the `signals` table. Going forward, adding a `review_reason` enum column (`corrupted_content`, `extraction_exhausted`, `discovery_unfetchable`, `clustering_ambiguous`) on `signals` would make this distinction explicit in schema rather than derived from relational history.

---

## 4. Explicit Non-Scope Status

- **Discovery Starvation:** Confirmed as a separate issue (56 rules running with 0 discovered articles). Documented for subsequent investigation.
- **Grounding Validation:** `check_grounding` rules in `ai/validate.py` were strictly untouched. Grounding rejections during extraction reflect valid defense against hallucinations.
- **Model Benchmarking Harness (`F`):** The model ladder refresh is an evidence-backed manual configuration; automated benchmarking belongs to Roadmap Item `F`.

---

## 5. Verification Gate Transcript

```powershell
corepack pnpm verify
```

```
$ corepack pnpm format:check && corepack pnpm lint && corepack pnpm typecheck && corepack pnpm test && corepack pnpm contracts:check && corepack pnpm build
$ uv run ruff format --check . && corepack pnpm --filter @episignal/web exec prettier --check .
190 files already formatted
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
Success: no issues found in 97 source files
$ corepack pnpm test:web && uv run pytest
$ corepack pnpm --filter @episignal/web test
$ vitest run

 RUN  v4.1.11 D:/Projects/Side Project/EpiSignal/.worktrees/extraction-fix/apps/web

 ✓ src/lib/api-signals.test.ts (3 tests) 43ms
 ✓ src/lib/radar-map-helpers.test.ts (7 tests) 51ms
 ✓ src/lib/api-health.test.ts (2 tests) 37ms
 ✓ src/lib/api-pipeline.test.ts (13 tests) 96ms
 ✓ src/lib/api-radar.test.ts (16 tests) 96ms
 ✓ src/components/signal-map.test.tsx (4 tests) 1010ms
 ✓ src/components/pipeline-monitor.test.tsx (5 tests) 1148ms
 ✓ src/components/home-shell.test.tsx (8 tests) 2228ms

 Test Files  8 passed (8)
      Tests  58 passed (58)

848 passed, 1 warning in 94.48s (0:01:34)
$ corepack pnpm contracts:generate && git diff --exit-code -- packages/contracts
$ uv run --package episignal-api python -m episignal_api.export_openapi && corepack pnpm --filter @episignal/contracts generate
wrote openapi.json
$ openapi-typescript openapi.json -o src/index.d.ts
$ corepack pnpm --filter @episignal/web build
$ next build
▲ Next.js 16.3.2 (Turbopack)
✓ Compiled successfully in 57s
```

```powershell
corepack pnpm db:check
```
```
database=up postgis=up
```

```powershell
git diff --check
```
Clean (no whitespace or line ending errors).
