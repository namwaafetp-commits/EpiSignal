# Lean MVP Real-Data Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prefer Mistral Small 24B for TRIAGE only, run one capped real-data surveillance window, and write an auditable MVP validation report.

**Architecture:** Keep production stages and persistence seams unchanged. Add one narrow ordering seam in the existing TRIAGE ladder construction so the selected model is first while existing fallback rungs and all other purpose routing remain intact. Capture live evidence through existing runners and read-only database/API checks; do not create benchmark infrastructure or product surfaces.

**Tech Stack:** Python, Pydantic model specs, pytest, PostgreSQL/SQLAlchemy, existing PowerShell pipeline runner, Next.js API/UI, pnpm/Corepack, uv.

---

### Task 1: Record design and bounded execution contract

**Files:**
- Create: `docs/superpowers/specs/2026-08-31-real-data-mvp-validation-design.md`
- Create: `docs/superpowers/plans/2026-08-31-real-data-mvp-validation.md`
- Modify: `STATUS.md` (position, active task ledger, next action)

- [x] **Step 1: Define fixed window and caps**

Use `2026-08-30T00:00:00Z` through `2026-08-31T00:00:00Z`, existing connectors, at most 200 raw candidates, and at most `$1.00` AI cost. Treat unsupported historical retrieval as a recorded deviation.

- [x] **Step 2: Define stop behavior**

Stop before the next stage on cap breach, critical triage false negative, repeated invented numbers, or false merge. Preserve rows; never manually edit or delete evidence.

- [x] **Step 3: Update task tracking**

Mark this validation item building and copy these tasks into `STATUS.md`; keep roadmap dependencies and production configuration unchanged.

### Task 2: Make Mistral first for TRIAGE only

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/triage.py`
- Test: `packages/backend/tests/test_ai_triage.py`

- [x] **Step 1: Add a failing focused test**

Add a repository fixture returning two TRIAGE-capable specs: Mistral Small 24B and Llama 3.1 8B. Run one valid triage request and assert `model.requests[0].model_id == "mistralai/mistral-small-24b-instruct-2501"`; assert the recorded request purpose is `AiPurpose.TRIAGE`.

- [x] **Step 2: Run focused test and confirm failure**

Run `uv run pytest packages/backend/tests/test_ai_triage.py -k mistral -v`. Before implementation, the current tier/order behavior must select the existing lower-tier Llama row.

- [x] **Step 3: Implement smallest ordering seam**

Define `TRIAGE_PREFERRED_MODEL_ID` in `triage.py`. After `Ladder.build(... purpose=AiPurpose.TRIAGE)`, move the matching rung to index zero while preserving the order of every other rung. If the preferred model is absent, use the existing ladder unchanged. Do not change `Ladder.build` semantics or any other purpose resolver.

- [x] **Step 4: Run focused and adjacent tests**

Run `uv run pytest packages/backend/tests/test_ai_triage.py packages/backend/tests/test_ai_ladder.py packages/backend/tests/test_event_judge.py -v`. Confirm fallback and event judge tests still pass.

### Task 3: Execute one capped real-data pipeline window

**Files:**
- No production source changes.
- Evidence source: database `pipeline_runs`, `signals`, `event_signals`, `event_observations`, `event_summaries`, and `ai_requests`.

- [x] **Step 1: Check prerequisites without printing secrets**

Run `corepack pnpm db:check` and verify required provider/database configuration exists by exit status only. Record failure type, not secret values.

- [x] **Step 2: Run existing stages with fixed caps**

Use the existing scheduled pipeline runner with environment overrides for a 1,440-minute GDELT window, at most 200 articles, at most 200 AI requests, and at most `$1.00`. If the runner’s stored cursor does not represent the requested completed interval, use existing stage runners with explicit `--window-minutes 1440` and record that limitation.

- [x] **Step 3: Capture exact stage output and run identifiers**

Record command lines excluding secret values, stdout counts, exit codes, pipeline run ID, stage timestamps, and any failed stage. Do not rerun a successful stage solely to change counts.

### Task 4: Inspect real outputs and public surfaces

**Files:**
- Evidence source: read-only database queries and existing API/UI.

- [x] **Step 1: Evaluate triage sample**

Inspect up to 20 relevant and 20 filtered signals. Check outbreak retention, unknown illness, irrelevant categories, public-health actions, schema/repair outcomes, and obvious false negatives.

- [x] **Step 2: Evaluate extraction sample**

Inspect 20–30 accepted extractions when available. Check number support, explicit zero versus null, disease and geography support, event/data-as-of dates, and every numeric fact’s source span.

- [x] **Step 3: Evaluate event and observation history**

Inspect all ambiguous matches when small and 10–20 events when available. Check false merges/splits and at least one multi-report event for preserved prior observations, source provenance, latest state, and timestamps.

- [x] **Step 4: Evaluate summaries and API/UI**

Inspect 10–15 summaries when available for grounded disease, geography, counts, dates, updates, uncertainty, and source IDs. Check event list, detail, sources, observations, and summary history through existing API/UI routes without redesign.

### Task 5: Write report and completion evidence

**Files:**
- Create: `docs/reports/2026-08-31-real-data-mvp-validation.md`
- Modify: `STATUS.md` (task ticks and verified baseline)

- [x] **Step 1: Write compact report**

Use required sections and exact verdict vocabulary: `MVP READY`, `MVP READY WITH MINOR FIXES`, or `MVP BLOCKED`. Include funnel, AI quality, event quality, observations, summaries, API/UI, cost, commands, deviations, and no more than three blockers.

- [x] **Step 2: Record provenance and limitations**

Include database/API query time, source and event identifiers, model IDs, cost-row totals, sample sizes, and any unavailable or unsupported check. Never include credentials or article bodies beyond short source spans needed for audit.

- [x] **Step 3: Commit implementation and report**

Commit focused code/test changes and report/tracking updates on `codex/real-data-mvp-validation`; do not merge or create a PR.

### Task 6: Run required gates and review

**Files:**
- No additional product changes after gates pass.

- [x] **Step 1: Run full verification**

Run `corepack pnpm verify`. Record exact web/Python test counts, xfails, and failures in the report and `STATUS.md`.

- [x] **Step 2: Run pipeline fixture gate**

Run `corepack pnpm test:pipeline`. Record exact result and xfail count.

- [x] **Step 3: Review diff on `main` baseline**

Inspect standards and spec compliance for `git diff main...HEAD`; fix only findings within task scope, then rerun affected gates.

- [x] **Step 4: Stop for review**

Return branch and commit, state no PR/merge was made, and identify any next corrective item without implementing it.
