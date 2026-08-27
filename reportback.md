# Sub-Project A: GDELT Discovery Layer — Reportback

## Executive Summary

Sub-project A (GDELT Discovery Layer) of the EpiSignal ingestion architecture is **complete and verified**. All 17 tasks from the implementation plan have been executed following strict Test-Driven Development (TDD), verified against the live GDELT API and database, and committed to branch `feat/gdelt-discovery`.

- **Branch:** `feat/gdelt-discovery`
- **Base:** `main` (commit `89a4d57`)
- **Head:** `8745923`
- **Total Commits:** 18 commits
- **Test Suite Status:** 296 passing tests, 0 failures, 0 regressions
- **Quality Gates:** `ruff check`, `ruff format`, and `mypy` passing 100%

---

## Task Completion Ledger

| Task | Description | Status | Primary Artifacts / Modules | Commit |
|:---|:---|:---:|:---|:---:|
| **1** | Add discovery vocabulary | Done | `db/types.py` (`DiscoveryMethod`) | `ee33506` |
| **2** | Map GDELT locale names to codes | Done | `ingestion/gdelt/locale.py` | `40ee0bc` |
| **3** | Add query rule model | Done | `models/discovery.py` (`GdeltQueryRule`) | `a30dce6` |
| **4** | Record discovery provenance | Done | `models/signal.py`, `models/catalog.py` | `ac7a259` |
| **5** | Schema migration | Done | `20260827_0003_gdelt_discovery.py` | `ca6ead9` |
| **6** | Seed query library | Done | `database/seeds/gdelt_queries.json` (56 rules), `seeds.py` | `45bc09f` |
| **7** | Discovery contracts | Done | `ingestion/documents.py` (DTOs) | `68534fa` |
| **8** | Discovery boundaries | Done | `ingestion/protocol.py` (Protocols) | `a7c6f56` |
| **9** | Extract page metadata | Done | `ingestion/gdelt/extract.py` | `f76fb54` |
| **10** | GDELT DOC 2.0 API client | Done | `ingestion/gdelt/api.py` | `40041f6` |
| **11** | Polite article fetcher | Done | `ingestion/gdelt/article.py` (`robots.txt`, delay) | `56b2a0d` |
| **12** | Assemble connector | Done | `ingestion/gdelt/connector.py` (`GdeltConnector`) | `966e42c` |
| **13** | Discovery pipeline | Done | `ingestion/discovery.py` (`run_discovery`) | `046ef98` |
| **14** | Signal repository | Done | `ingestion/repository.py` (`SqlAlchemyDiscoveryRepository`) | `f46dd29` |
| **15** | Stub retry pass | Done | `ingestion/discovery.py` (`run_retry`) | `340b839` |
| **16** | Runner CLI & config | Done | `discover_runner.py`, `config.py`, `package.json` | `924f92f` |
| **17** | Live API & DB verification | Done | Live test verification, documentation updates | `8745923` |

---

## Architectural Guarantees & Invariants

1. **Source Attribution:**
   - Outlets discovered via GDELT are registered as `Source` records with `source_type=LOCAL_MEDIA`, `credibility_tier=UNKNOWN`, and `is_official=False`.
   - GDELT is never attributed as the source of record in the database or UI.
2. **Timestamp Provenance:**
   - Four distinct timestamps are tracked without substitution:
     - `published_at` (with `published_at_offset_minutes`): publication instant from publisher HTML.
     - `first_seen_at`: initial discovery instant (preserved forever across retries).
     - `retrieved_at`: instant this specific document payload was scraped.
     - `gdelt_seen_at`: 15-minute quantized crawler sighting timestamp from GDELT.
3. **Deduplication:**
   - Discovered URLs are canonicalized and checked against existing database rows before any publisher connection is opened.
4. **Resilience & Politeness:**
   - Dedicated `robots.txt` compliance per domain with domain-scoped request delays.
   - Failed page fetches store stub signals (`processing_status=NEEDS_REVIEW`) and are retried via `pnpm discover:gdelt` up to `max_retrieval_attempts`.

---

## CLI & Pipeline Commands

```powershell
# Run GDELT discovery polling tick
pnpm discover:gdelt

# Run GDELT discovery with explicit window or batch limits
pnpm discover:gdelt -- --window-minutes 1440 --max-articles 50

# Seed database with initial query library
pnpm db:seed

# Run official source ingestion (remains isolated & intact)
pnpm ingest:who
pnpm ingest:ecdc

# Verify all quality gates
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy apps/api/src packages/backend/src
```

---

## Next Steps for Subsequent Sub-Projects

The sub-project boundaries are fixed by
`docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md`, which is the
authority on what each letter covers.

- **Sub-Project B (Stage 0: deduplication and rule filtering):**
  - Reject obviously irrelevant articles from GDELT metadata before any page fetch.
  - Resolve syndicated copies to one primary signal per story, before any AI call.
  - Designed in `docs/superpowers/specs/2026-08-27-gdelt-stage0-filtering-design.md`.
- **Sub-Project C (AI: classification, extraction, escalation, cost logging):**
  - Read signals with `processing_status='normalized'`.
  - Extract disease entities, locations, date ranges, and case/fatality counts from `raw_text`.
- **Sub-Project D (Story clustering, event matching, dual scoring):**
  - Cluster multi-source signals (WHO, ECDC, GDELT local media) into deduplicated `Event` records.
  - Preserve provenance linking observations back to individual signals.
  - Compute `early_signal_score` and `evidence_score` separately, never merged.
