# Sub-project M Completion Report: Manual Review Queue

## Summary

Sub-project `M` provides a durable, typed manual review workspace for triage of unclusterable, ambiguous, failed, or quarantined signals. It replaces open-ended or unclassified `needs_review` statuses with typed `SignalReviewCase` records, atomic resolution state machines, a hardened admin review API, and a dark navy/cyan operator workspace mounted at `/admin/reviews`.

---

## 1. Task & Commit Ledger

| Task | Description | Status | Commit |
|---|---|---|---|
| **1** | Design durable typed review schema (`0014_manual_review_cases.py`) | Verified | `625aa65` |
| **2** | Classify and backfill existing `needs_review` signals | Verified | `30a6e0c` |
| **3** | Guard irreversible downgrade of resolved review cases | Verified | `9ea63a0` |
| **4** | Define domain command models and closed reason-action matrix | Verified | `ca8a7b9` |
| **5** | Add review case persistence, query builder, and optimistic locking | Verified | `5aa02ba` |
| **6** | Extract shared event finalization implementation (`finalize.py`) | Verified | `1ff9bf2` |
| **7** | Implement transactional resolution for retry, disease, and dismissal | Verified | `4b0ebf4` |
| **8** | Implement transactional ambiguous event linking and creation | Verified | `21a7fe5` |
| **9** | Add constant-time admin token authentication & secure settings | Verified | `c21d1b3` |
| **10** | Expose authenticated review queue listing endpoint | Verified | `d85264b` |
| **11** | Expose transactional resolution route & regenerate contracts | Verified | `022f031` |
| **12** | Implement runtime-validated review API client in web package | Verified | `8ec2182` |
| **13** | Build accessible, cause-specific review console component | Verified | `8ffabb1` |
| **14** | Mount review workspace at `/admin/reviews` and add masthead navigation | Verified | `3cce127` |
| **15** | Review, verify, capture safe live proof, and report | Verified | *(current)* |

---

## 2. Schema Forward & Guarded Rollback Evidence

### Migration `20260829_0014_manual_review_cases`

1. **Tables & Indexes**:
   - `signal_review_cases`: stores durable cases keyed by `id` (UUID PK), foreign key `signal_id` referencing `signals.id` (CASCADE).
   - Partial unique index `ix_signal_review_cases_open_signal` on `(signal_id) WHERE status = 'open'` enforces at most one open case per signal.
   - Index `ix_signal_review_cases_opened_at` on `(opened_at, id)` guarantees deterministic oldest-first queue ordering.
   - `signal_review_candidates`: stores snapshot of candidate events (`review_case_id`, `event_id`, `match_score`) captured at moment of ambiguous match.

2. **Guarded Downgrade**:
   - Downgrade queries `SELECT count(id) FROM signal_review_cases WHERE status = 'resolved'`.
   - If any resolved cases exist, raises a loud `RuntimeError` preventing silent loss of operator decision history unless all cases are open.

---

## 3. Live Pre/Post Case Reconciliation

Query executed against live Postgres database:
- **Total `signals` with `processing_status = 'needs_review'`**: 64
- **Total open `signal_review_cases`**: 64 (1:1 exact bijection)
- **Reason Breakdown**:
  - `retrieval_failed`: 34 cases (allowed actions: `retry_retrieval`, `dismiss`)
  - `disease_unresolved`: 28 cases (allowed actions: `assign_disease`, `dismiss`)
  - `legacy_unclassified`: 1 case (allowed actions: `dismiss`)
  - `content_integrity`: 1 case (quarantined signal `852aa204-...`; allowed actions: `dismiss`)
- **Cardinality Checks**:
  - Signals with `<> 1` open case: 0
  - Open cases pointing to non-`needs_review` signals: 0

---

## 4. Authentication, Security, and Forbidden-Field Scan Proof

1. **Admin Token Authentication**:
   - Accepts token via `Authorization: Bearer <token>` or `X-Admin-Token: <token>`.
   - Compares secret using `secrets.compare_digest` in constant time against `EPISIGNAL_ADMIN_TOKEN`.
   - If unconfigured, securely rejects all requests (503 Service Unavailable).

2. **Secret Scan**:
   - Scan for hardcoded credentials (`git grep -n -I -E 'EPISIGNAL_(ADMIN_TOKEN|OPENROUTER_API_KEY)=.+'`): 0 real secrets found in repository.

3. **Forbidden Field Scan**:
   - Scan for `raw_text`, `source_span`, `prompt`, `api_key`, `exception`:
   - Excluded from API response models (`ReviewQueueItem`, `ReviewQueuePage`).
   - Explicitly validated and rejected in web client (`apps/web/src/lib/api-reviews.ts` `FORBIDDEN_KEYS`).
   - No patient-level or raw unredacted source text exposed to the UI.

---

## 5. Event Finalization Parity Proof

Extracted unified finalization logic into `episignal_backend.events.finalize.finalize_signal_event`:
- Single source of truth for:
  - Event title assignment / update
  - Summary brief accumulation and delta calculation
  - Score computation (early signal score & evidence score)
  - `EventSignal` link creation and signal advancement to `processing_status = 'matched'`
- Used identically by:
  - Automated ingestion pipeline (`EventRunner` / `EventAssembler`)
  - Manual review resolver (`SqlAlchemyReviewRepository.resolve_review`) for `link_event` and `create_event` actions.

---

## 6. Verification Gate Results (`corepack pnpm verify`)

- **Format Check**: 226 files formatted, Prettier code style clean (`exit 0`).
- **Linters**:
  - Web ESLint: 0 errors, 0 warnings (`exit 0`).
  - Python Ruff: All checks passed (`exit 0`).
- **Typecheckers**:
  - Web TypeScript (`tsc --noEmit`): Clean (`exit 0`).
  - Python Mypy: `Success: no issues found in 113 source files` (`exit 0`).
- **Automated Tests**:
  - Web Vitest: 10 test files, 75 passed (`exit 0`).
  - Python Pytest: 949 passed, 2 warnings (`exit 0`).
- **Contract Parity**: OpenAPI spec exported and TypeScript definitions generated; `git diff --exit-code -- packages/contracts` is clean (`exit 0`).
- **Production Build**: Next.js 16.3.2 built production bundle including static route `/admin/reviews` (`exit 0`).

---

## 7. Limitations & Deliberately Omitted Live Mutations

- In accordance with conservative safety policies, no live signals were mutated, dismissed, or linked solely for proof.
- Transactional resolution concurrency, lock contention, and rollback behaviors are fully verified via integration tests (`apps/api/integration_tests/test_review_resolution_concurrency.py` and `apps/api/integration_tests/test_manual_review_migration.py`).
