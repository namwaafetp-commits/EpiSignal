# Surveillance Dimensions and Flexible Event Summaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add disease-group and host-sector dimensions plus flexible, backward-compatible event summaries across backend, API, and dashboard.

**Architecture:** Disease group is derived from one explicit canonical-disease registry. Host sector is classified by DeepSeek and stored additively on signals, then derived on events. Summaries use a strict 3–5 bullet contract while old persisted summaries keep a fallback renderer.

**Tech Stack:** Python, Pydantic, SQLAlchemy/Alembic, FastAPI, generated OpenAPI/TypeScript contracts, Next.js/React, Vitest, pytest, Ruff, pnpm.

**Spec:** `docs/superpowers/specs/2026-09-08-surveillance-dimensions-and-flexible-summaries-design.md`

## Global Constraints

- Preserve `DISCOVER → dedup → DeepSeek classify → retrieve → Gemini disease/location → deterministic normalization/grouping → Mistral summary`.
- Do not change event matching thresholds, false-merge policy, GDELT behavior, monitoring thresholds, scheduler behavior, map coordinates, or Gemini responsibilities.
- Missing historical host-sector values resolve to `unknown`.
- Do not perform historical AI backfill or production operations.
- Disease groups are EpiSignal's standard surveillance grouping, not an official WHO taxonomy.

---

### Task 1: Disease-group domain registry

**Files:**
- Create: `packages/backend/src/episignal_backend/disease_groups.py`
- Modify: `packages/backend/src/episignal_backend/db/repository.py` or the existing disease repository seam that resolves canonical diseases
- Test: `packages/backend/tests/test_disease_groups.py`

**Interfaces:**
- Produces `DiseaseGroup`, `DISEASE_GROUP_LABELS`, `CANONICAL_DISEASE_GROUPS`, `disease_group_for(canonical_slug: str | None) -> DiseaseGroup`, and `disease_group_label(group: DiseaseGroup) -> str`.
- Consumes the existing canonical disease slug/name resolver; does not alter normalization or alias resolution.

- [ ] **Step 1: Write failing registry tests** for every current canonical disease in `database/seeds/diseases.json`, exact one-to-one coverage, stable labels, alias-before-group behavior through the existing resolver, and unknown fallback.
- [ ] **Step 2: Run** `corepack pnpm --filter backend exec pytest packages/backend/tests/test_disease_groups.py -q`; expect failures for missing registry symbols.
- [ ] **Step 3: Implement** the enum, labels, and explicit mapping in one file. Add a coverage assertion/test helper that rejects duplicate or unmapped current canonical slugs without changing runtime keyword behavior.
- [ ] **Step 4: Run the focused test file** and confirm all mapping and alias tests pass.
- [ ] **Step 5: Commit** with `feat: add deterministic disease surveillance groups`.

### Task 2: Host-sector classification contract

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/schema.py`
- Modify: `packages/backend/src/episignal_backend/ai/prompts.py`
- Modify: `packages/backend/src/episignal_backend/ai/classify.py`
- Modify: `packages/backend/src/episignal_backend/ai/documents.py` and the classification repository protocol/implementation
- Test: `packages/backend/tests/test_ai_classify.py`, `packages/backend/tests/test_ai_schema.py`, `packages/backend/tests/test_ai_prompts.py`

**Interfaces:**
- Produces `HostSector` with values `human`, `animal`, `both`, `unknown` and `ClassificationVerdict.host_sector`.
- Existing relevance classification remains the only DeepSeek call; Gemini extraction remains unchanged.

- [ ] **Step 1: Add failing tests** for each host-sector value, ambiguous evidence, zoonotic-name-only input resolving to unknown, strict JSON schema, and prompt rules that require explicit human and animal evidence.
- [ ] **Step 2: Run focused AI tests** and confirm failures show missing field/schema behavior.
- [ ] **Step 3: Implement** the enum, strict Pydantic field defaulting missing/blank values to unknown, prompt guidance, and storage handoff through existing classification seams.
- [ ] **Step 4: Run focused AI tests** and confirm old classification fixtures without the new field remain accepted as unknown where backward compatibility requires it.
- [ ] **Step 5: Commit** with `feat: classify signal host sector`.

### Task 3: Additive signal persistence and event derivation

**Files:**
- Create: `database/migrations/versions/<new_revision>_signal_host_sector.py`
- Modify: signal SQLAlchemy model/table definition, signal repository documents/protocol, and event documents/read repository
- Test: `packages/backend/tests/test_event_host_sector.py`, `apps/api/tests/test_migrations.py`, relevant repository tests

**Interfaces:**
- Produces `derive_event_host_sector(values: Iterable[HostSector]) -> HostSector` with explicit precedence.
- Signal reads expose missing/null historical storage as `HostSector.UNKNOWN`.
- Migration is additive and follows previous head `20260904_0022`.

- [ ] **Step 1: Write failing derivation tests** for human-only, animal-only, both-only, human plus animal, human plus unknown, animal plus unknown, and unknown-only.
- [ ] **Step 2: Run focused tests** and confirm missing derivation/persistence behavior.
- [ ] **Step 3: Implement** the pure derivation function and nullable signal column/repository wiring. Do not write a backfill.
- [ ] **Step 4: Add migration-head and missing-value compatibility tests**, then run them.
- [ ] **Step 5: Commit** with `feat: persist signal host sector additively`.

### Task 4: Flexible summary contract and compatibility renderer

**Files:**
- Modify: `packages/backend/src/episignal_backend/events/summarize.py`
- Modify: summary persistence/wiring documents and repository code as required by the existing `event_summaries` JSON contract
- Test: `packages/backend/tests/test_event_summarize.py`

**Interfaces:**
- Produces `FlexibleEventSummary(title: str, bullets: tuple[str, ...], takeaway: str)` with 3–5 bullets.
- `run_summary` accepts only the new strict shape for new model responses.
- Renderer handles both new payloads and existing headline/trajectory/snapshot/key-driver/response/risk payloads.

- [ ] **Step 1: Write failing tests** for 3 and 5 bullets accepted; fewer/more bullets, blank title/takeaway, malformed JSON, fixed-heading-free output, and legacy summary rendering.
- [ ] **Step 2: Run focused summary tests** and confirm current rigid contract fails the new expectations.
- [ ] **Step 3: Implement** the new Pydantic contract, Mistral prompt, JSON schema, strict validation, title preservation from canonical event metadata, and compatibility fallback without fabricating facts.
- [ ] **Step 4: Run focused summary tests** and confirm old fixtures still render and new fixtures render as title, bullets, takeaway.
- [ ] **Step 5: Commit** with `feat: support flexible event summaries`.

### Task 5: API fields, filters, and generated contracts

**Files:**
- Modify: `apps/api/src/episignal_api/routes/events.py`, signal/radar route seams, and backend read services
- Modify: `apps/api/tests/test_events_api.py`, `apps/api/tests/test_radar_api.py`, `apps/api/tests/test_openapi.py`
- Regenerate: `packages/contracts/openapi.json`, `packages/contracts/src/index.d.ts`

**Interfaces:**
- API exposes `disease_group`, `disease_group_label`, and `host_sector` additively.
- Host filter semantics: Human matches `human` and `both`; Animal matches `animal` and `both`; All includes all values including unknown.
- Disease-group filter combines with host filter without changing existing filters.

- [ ] **Step 1: Add failing API tests** for additive fields, unknown compatibility, each host filter, each group filter, and combined filters.
- [ ] **Step 2: Run focused API tests** and confirm missing fields/filters.
- [ ] **Step 3: Implement** derived group fields, event host derivation, filter validation, and backward-compatible response serialization.
- [ ] **Step 4: Regenerate contracts and run OpenAPI/route tests**; confirm schema matches runtime responses.
- [ ] **Step 5: Commit** with `feat: expose surveillance dimensions in API`.

### Task 6: Dashboard filters and summary/card rendering

**Files:**
- Modify: `apps/web/src/lib/api-events.ts`, `apps/web/src/lib/api-dashboard.ts`
- Modify: `apps/web/src/components/home-shell.tsx`, event page/detail components, and targeted styles
- Test: `apps/web/src/components/home-shell.test.tsx`, `apps/web/src/app/events/[publicId]/page.test.tsx`, API client tests

**Interfaces:**
- UI filters expose `All | Human | Animal` and the controlled disease-group labels.
- Cards/details show disease, disease group, and host badge where available.
- New summaries show title, 3–5 bullets, and takeaway; legacy summary text remains visible.

- [ ] **Step 1: Add failing component tests** for host filter inclusion, group filter combination, metadata badges, new summary rendering, and old-summary fallback.
- [ ] **Step 2: Run focused web tests** and confirm missing controls/rendering.
- [ ] **Step 3: Implement** client types, local filtering/URL query wiring consistent with existing dashboard behavior, compact metadata, and summary compatibility rendering.
- [ ] **Step 4: Run focused web tests, lint, and typecheck** for changed files.
- [ ] **Step 5: Commit** with `feat: add host and disease group dashboard filters`.

### Task 7: Full review, verification, and completion report

**Files:**
- Modify: `STATUS.md` task ledger and verified baseline
- Create: `docs/reports/2026-09-08-surveillance-dimensions-report.md`

- [ ] **Step 1: Run focused backend/API/web tests, Ruff, frontend lint/typecheck, migration/OpenAPI checks.** Record exact results.
- [ ] **Step 2: Run `corepack pnpm verify`; do not claim completion unless it reports zero failures.**
- [ ] **Step 3: Review diff from baseline `19a48878ee03e5548af8db6f842bf165ec70a90e` against standards and feature requirements.** Resolve only in-scope findings.
- [ ] **Step 4: Write completion report** with architecture, complete disease mapping counts, schema/migration head, API/UI changes, exact test results, invariants, git state, and explicit no-deployment statements.
- [ ] **Step 5: Commit report/status updates, then push `codex/next-iteration`** if remote access remains local repository git only.

## Self-review

- Disease grouping, host classification, event derivation, summary validation, API fields, filters, UI rendering, and backward compatibility each have an explicit task.
- No task changes event matching, monitoring, scheduler, GDELT, coordinates, or Gemini responsibilities.
- Unknown and legacy paths are tested before claiming completion.
