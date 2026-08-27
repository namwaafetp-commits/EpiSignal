# Sub-Project D1 Completion Report: Geocoding Extracted Places

**Date:** 2026-08-27  
**Repository:** `EpiSignal` (`namwaafetp-commits/EpiSignal`)  
**Base Commit:** `2f01d31`  
**Head Commit:** `4277809`  

---

## 1. Executive Summary

Sub-Project D1 of EpiSignal introduces deterministic, provenance-preserving geocoding of extracted outbreak locations against a normalized GeoNames gazetteer. All 21 tasks specified in `docs/superpowers/plans/2026-08-27-geocoding.md` have been implemented test-first via strict TDD red-green cycles, verified against live PostgreSQL/PostGIS, and validated through the complete workspace verification gate.

Key architectural guarantees enforced across the subsystem:
1. **Ambiguity Coarsens, Never Tie-Breaks:** When an extracted place matches multiple candidate locations in a province or country, the resolver never selects the largest or most populous candidate. Instead, it coarsens to the administrative division (admin1 or country) centroid, preserving semantic truth over guessed precision. `Candidate` structurally excludes population data so tie-breaking is impossible.
2. **Strict Country Scoping & Aliasing:** Country names are resolved against a curated, normalized alias dataset before scoping sub-national queries. Place searches inside a country never escape to match homonyms in other countries.
3. **Purity of Seams:** Decision modules (`documents.py`, `normalize.py`, `resolve.py`, `protocol.py`, `locate.py`) contain 0 imports of SQLAlchemy or network drivers. Only `geocode/repository.py` handles database access, and 0 network requests are made during runtime geocoding.
4. **Transparent Location Provenance:** `signal_locations` stores the original extracted text strings alongside the matched GeoNames ID, resolved name, administrative codes, geographic coordinates, PostGIS geometry point, confidence score, and geocoding source tag. Unresolved places store null coordinates and null confidence rather than arbitrary zeros.
5. **Deterministic Seed Generation:** `scripts/build_gazetteer.py` transforms GeoNames dump files (`countryInfo.txt`, `admin1CodesASCII.txt`, `admin2Codes.txt`, `cities1000.txt`) into a reproducible, sorted `gazetteer_places.tsv.gz` artifact (208,059 rows, 10.4 MB) with deterministic gzip headers (`mtime=0.0`).

---

## 2. Completed Tasks Ledger

| Task | Commit | Description |
|:---|:---|:---|
| 1 | `81f11f9` | Location precision vocabulary enum (`Precision`: `place`, `admin2`, `admin1`, `country`, `unresolved`) |
| 2 | `7de30c3` | Contracts for gazetteer and storage seams (`MatchForm`, `ExtractedPlace`, `Candidate`, `ResolvedLocation`, `GeocodableSignal`) |
| 3 | `14d243d` | Exact and diacritic-folded name forms (`normalized_form`, `ascii_form`) |
| 4 | `b4567d7` | Country name resolution through reviewed alias map (`resolve_country`) |
| 5 | `45ad990` | Storage boundary protocols (`GazetteerRepository`, `GeocodeRepository`, `GazetteerMissing`) |
| 6 | `447ceca` | Geocoding confidence derivation based on match method (`confidence_for`) |
| 7 | `2b10e0e` | Scoped unique place matching ladder (`_unique_match`, `_accept`, `resolve_place`) |
| 8 | `53cefef` | Hierarchical coarsening for ambiguous candidates (`_coarsen`, `_unresolved`) |
| 9 | `3aac144` | Global fallback resolution for country-less extractions (`_worldwide`) |
| 10 | `692363d` | SQLAlchemy models `GazetteerPlace` and `SignalLocation` with GIST spatial index |
| 11 | `8c8b90b` | Alembic migration `20260827_0006_geocoding` with clean rollback |
| 12 | `be60c57` | Deterministic GeoNames gazetteer build script and unit test fixtures |
| 13 | `3544381` | Seed dataset for 75 reviewed country aliases and CC BY 4.0 attribution |
| 14 | `6e32bf9` | Batch streaming gazetteer seeder and seed runner extension |
| 15 | `e633990` | `SqlAlchemyGazetteerRepository` storage adapter |
| 16 | `18ad949` | `SqlAlchemyGeocodeRepository` storage adapter |
| 17 | `4ba993a` | Orchestration loop and signal state progression (`run_geocoding`) |
| 18 | `8c9e459` | Geocoding configuration settings and batch size validation |
| 19 | `6eb13a6` | CLI runner `geocode_runner.py` and `geocode:signals` script |
| 20 | `1564aa8` | Architectural seam test guards and expected schema test updates |
| 21 | `4277809` | Live GeoNames dump download, gazetteer generation, migration, seeding, and live DB validation |

---

## 3. Verification and Quality Gates

All verification gates ran and passed:

1. **Python Unit & Integration Test Suite (`uv run pytest`):**
   - **Result:** `618 passed, 1 warning in 27.82s`
   - **Isolation:** 0 unit tests make socket connections or rely on unseeded external databases.
2. **Linting & Code Style (`uv run ruff check .`):**
   - **Result:** `All checks passed!`
3. **Code Formatting (`uv run ruff format --check .`):**
   - **Result:** `139 files already formatted`
4. **Static Type Checking (`uv run mypy apps/api/src packages/backend/src`):**
   - **Result:** `Success: no issues found in 73 source files`
5. **Web & Monorepo Verification:**
   - **Prettier:** `corepack pnpm --filter @episignal/web exec prettier --check .` -> PASS
   - **Web Lint:** `corepack pnpm --filter @episignal/web lint` -> PASS
   - **Web Typecheck:** `corepack pnpm --filter @episignal/web typecheck` -> PASS
   - **Web Tests:** `corepack pnpm --filter @episignal/web test` -> 10 passed (10)
   - **Web Build:** `corepack pnpm --filter @episignal/web build` -> Next.js production build succeeded
   - **API Contracts:** `openapi-typescript openapi.json` -> Schema diff clean
6. **Live Database Verification:**
   - Migration `20260827_0006_geocoding` applied and rollback/re-upgrade verified.
   - Seeded 208,059 gazetteer places from generated artifact.
   - Live execution of `geocode:signals` and `--stale` idempotence verified on PostgreSQL with PostGIS.

---

## 4. Two-Axis Code Review Summary (`2f01d31...HEAD`)

### Standards Axis
- **Hard Violations:** 0.
- **Architectural Conformance:** Strict isolation of decision modules from database drivers; zero network dependencies in geocoding ladder; non-tie-breaking invariant enforced structurally; reproducible seed artifact generation verified.
- **Review Notes:** 
  - `Candidate` model strictly omits population field to enforce the anti-tie-breaking policy at the type level.
  - Streaming iterator in `read_gazetteer` avoids loading 200k rows into memory during database seeding.

### Spec Axis
- **Requirements Coverage:** 100% of 21 planned tasks implemented and tested against acceptance criteria.
- **Design Invariants:** All 13 acceptance criteria from `docs/superpowers/specs/2026-08-27-geocoding-design.md` verified with dedicated tests.
- **Known Items Carried Forward:**
  - Extracted locations carry no `source_span` from the extraction stage (unavoidable without re-extraction schema change).
  - Reconciling `events.attention_score` and `events.confidence_score` with `early_signal_score` / `evidence_score` remains an explicit task for Sub-Project D2.

---

## 5. Conclusion

Sub-Project D1 is complete and fully verified. `signal_locations` is populated, spatially indexed with PostGIS, and ready to serve as the spatial foundation for Sub-Project D2 (story clustering, event matching, and dual scoring).
