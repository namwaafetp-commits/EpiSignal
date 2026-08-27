# Sub-Project B: Stage 0 Deduplication and Rule Filtering — Report

## Executive Summary

Sub-project B (Stage 0 Deduplication and Rule Filtering) of the EpiSignal ingestion architecture is **complete, verified end-to-end, and merged into main**. All 13 tasks from the implementation plan have been executed test-first (TDD), verified against live GDELT discovery and live PostgreSQL database passes, and committed.

- **Branch:** `feat/gdelt-stage0`
- **Base:** `main` (commit `c960b2c`)
- **Total Commits on Branch:** 16 commits
- **Test Suite Status:** 357 passing tests, 0 failures, 0 regressions
- **Quality Gates:** `ruff check`, `ruff format`, and `mypy` passing 100% across 51 source files
- **Commands Added:** `pnpm dedupe:signals` (`corepack pnpm dedupe:signals`)

---

## Task Completion Ledger

| Task | Description | Status | Primary Artifacts / Modules | Commit |
|:---|:---|:---:|:---|:---:|
| **1** | Vocabulary for filter groups and duplicate status | Done | `db/types.py` (`FilterRuleGroup`, `ProcessingStatus.DUPLICATE`) | `e94c8eb` |
| **2** | Contracts for rules, rejections, and comparable signals | Done | `ingestion/documents.py` (`FilterRule`, `Rejection`, `ComparableSignal`) | `40ddda3` |
| **3** | Models for filter rules, rejections, duplicate pointer | Done | `models/discovery.py`, `models/signal.py`, `models/__init__.py` | `1983d7f` |
| **4** | Migration 20260827_0004 | Done | `database/migrations/versions/20260827_0004_stage0_filtering.py` | `c37e969` |
| **5** | Relevance filter pure module | Done | `ingestion/filtering.py` (`compile_rules`, `evaluate`) | `9cc7924` |
| **6** | Title and body similarity | Done | `ingestion/similarity.py` (Jaccard shingles, furniture stripping) | `27579c2` |
| **7** | Seeded rule library | Done | `database/seeds/filter_rules.json` (12 rules), `seeds.py` | `5705134` |
| **8** | Storage for rules and rejections | Done | `ingestion/protocol.py`, `ingestion/repository.py` | `2a805a9` |
| **9** | Gate one inside discovery run | Done | `ingestion/discovery.py`, `discover_runner.py` | `5f82055` |
| **10** | Deduplication pass pure module | Done | `ingestion/dedupe.py` (`run_dedupe`, `matches`, `precedes`) | `432ea2d` |
| **11** | Storage for deduplication pass | Done | `ingestion/repository.py` (`SqlAlchemyDedupeRepository`) | `4f5b275` |
| **12** | Configuration and runner command | Done | `config.py`, `dedupe_runner.py`, `package.json` | `50a20df` |
| **13** | Live verification & quality gates | Done | `README.md`, full test gates, live pipeline smoke | `3461fcd` |

---

## Architectural Guarantees & Invariants Preserved

1. **Gate One: Negative-Only Relevance Filtering**
   - Articles matching compiled title regex exclusions or blocklisted domains are dropped before opening any publisher connection.
   - Every rejection writes an audit row in `rejected_sightings` linking the `filter_rule_id`.
   - Gate 1 runs before the per-run fetch cap, preventing budget waste on junk.
   - Negative-only rule: never rejects an article for failing to prove relevance.

2. **Gate Two: Conservative Deduplication**
   - Resolves syndicated copies to one primary signal per story.
   - Never merges on title alone: requires identical content hash or high similarity on both title ($\ge 0.90$) and body ($\ge 0.80$).
   - Primary signal is the earliest sighting (`first_seen_at`), tie-broken by `published_at` and UUID.
   - Duplicate pointers are flattened on write (`duplicate_of_signal_id`), guaranteeing zero pointer chains (`chained = 0`).
   - Idempotent: re-running `dedupe:signals` examines 0 new rows.

3. **Pure Module Isolation**
   - `filtering.py`, `similarity.py`, and `dedupe.py` contain zero SQLAlchemy/httpx dependencies, tested with fast in-memory fakes.

4. **Zero Out-of-Scope Leakage**
   - No AI or embedding calls were added.
   - WHO and ECDC ingestion remain completely untouched and passing.

---

## Environment & Run Commands

- **Run GDELT Discovery**: `corepack pnpm discover:gdelt`
- **Run Signal Deduplication**: `corepack pnpm dedupe:signals`
- **Seed Database**: `corepack pnpm db:seed`
- **Run Migrations**: `corepack pnpm db:migrate`
- **Run Test Suite**: `uv run pytest` (357 passed)
- **Run Typecheck**: `uv run mypy apps/api/src packages/backend/src`
- **Run Linters**: `uv run ruff check .` and `uv run ruff format --check .`

---

## Next Steps for the Next Agent (Sub-Project C)

Sub-project boundaries are governed by `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md`.

**Sub-Project C: AI: Batched Classification, Extraction, Escalation, Cost Logging**
- **Input:** Read signals with `processing_status = 'normalized'` (written by Stage 0 Gate 2).
- **Tasks to Design & Build:**
  1. Batched relevance classification with structured JSON output.
  2. Epidemiological extraction schema (pathogen/syndrome, suspected/confirmed counts, deaths, locations, temporal intervals).
  3. Multi-tier model escalation:
     - Tier 1: Free OpenRouter models (e.g. `meta-llama/llama-3.3-70b-instruct:free`, `google/gemini-2.0-flash-exp:free`).
     - Tier 2: Paid fallback / low-cost model (e.g. Gemini 2.0 Flash).
     - Tier 3: High-reasoning escalation for low-confidence / complex multilingual documents.
  4. Precise token and cost tracking table and audit logging.
