# Sub-Project E Completion Report: Signal Radar and Operational Monitoring

**Date:** 2026-08-28
**Repository:** `EpiSignal` (`namwaafetp-commits/EpiSignal`)
**Base Commit:** `7a753ce`
**Verification Gate:** `corepack pnpm verify` (exit code 0)

---

## 1. Executive Summary

Sub-Project E delivers the real-time Signal Radar and Operational Pipeline Monitoring for EpiSignal. The system surfaces recent epidemiological signals extracted from official health agencies and global media sources, coordinates interactive map and list representations, extracts 5-slot structured briefs without raw-text leakage, links attached outbreak events with dual independent scores, and provides read-only visibility into pipeline execution health.

All 15 tasks planned in `docs/superpowers/plans/2026-08-28-signal-radar.md` and subsequent review corrections were executed test-first using strict Test-Driven Development (red-green-refactor cycles), verified against live database and OpenAPI contracts, and validated through the complete workspace verification gate (`corepack pnpm verify`).

### Key Architectural Invariants Preserved:
1. **Representative Location Rule:** Coordinates are chosen strictly through the deterministic hierarchy: primary role preference > finest precision rank > lowest location UUID tie-breaker. Unresolved locations or incomplete coordinates yield `None` and display an explicit `📍 Location unresolved` badge. Population tables are never read.
2. **Source Standing Distinction:** Official standing is derived strictly from `source.is_official`. Non-official media sources are never labeled "Official Source" regardless of credibility tier. Credibility tier is displayed as a separate attribute (`Tier: {tier}`).
3. **Zero Raw Text or Secret Leaks:** Raw article text, internal AI prompts, API keys, exception tracebacks, and patient-level data are strictly excluded from radar read models and API schemas. Pipeline failure parsing strictly sanitizes error types to valid Python exception class names, converting arbitrary strings or URLs to null.
4. **5-Slot Structured Briefs:** Signals are rendered exclusively via the 5-slot brief (`what_where`, `counts`, `timing`, `spread`, `reporting`), preserving ground-truth facts while protecting source copyright and readability.
5. **Dual Independent Scoring Integrity:** `early_signal_score` (surveillance interest) and `evidence_score` (evidence support) on attached events remain distinct on the 0–1 scale and are never averaged or combined into a single badge.
6. **Read-Only Operational Monitoring:** Pipeline execution history is strictly read-only, presenting integer stage counts, backlogs, and sanitized error types without mutation controls, forms, or exception details.
7. **Accessible Map and List Equivalence:** The map provides spatial overview with interactive marker popups and graceful error fallbacks, while the card list remains the complete keyboard-accessible representation with independent external source navigation.

---

## 2. Completed Tasks Ledger

| Task | Description |
|:---|:---|
| 1 | Preserve exception types in pipeline history (`schedule/protocol.py`, `schedule/repository.py`, `pipeline_runner.py`) |
| 2 | Define the radar read contracts and representative location rule (`episignal_backend/radar.py`) |
| 3 | Query and assemble recent radar signals with bounded chunked pagination (`query_radar` in `episignal_backend/radar.py`) |
| 4 | Query counts-only pipeline history with error name sanitization (`query_pipeline_runs` in `episignal_backend/radar.py`) |
| 5 | Expose `GET /api/v1/radar` endpoint (`episignal_api/routes/radar.py`) |
| 6 | Expose `GET /api/v1/admin/pipeline-runs` endpoint (`episignal_api/routes/admin.py`) |
| 7 | Regenerate and lock API contracts (`openapi.json`, `index.d.ts`, `test_openapi.py`) |
| 8 | Strictly validate radar responses and strict ISO date-time strings in web client (`apps/web/src/lib/api-radar.ts`) |
| 9 | Add map dependencies and pure marker helpers (`apps/web/src/lib/radar-map-helpers.ts`) |
| 10 | Mount a small resilient MapLibre component with marker details (`apps/web/src/components/signal-map.tsx`) |
| 11 | Replace homepage with radar map, 5-slot cards, and keyboard selection (`apps/web/src/components/home-shell.tsx`) |
| 12 | Wire server fetching, loading, responsive CSS, and build safety (`app/page.tsx`, `app/loading.tsx`) |
| 13 | Strictly validate pipeline history in the web client (`apps/web/src/lib/api-pipeline.ts`) |
| 14 | Build read-only pipeline monitor page (`apps/web/src/components/pipeline-monitor.tsx`, `app/admin/pipeline/page.tsx`) |
| 15 | Review, full gate, live proof, and completion report |

---

## 3. Verification and Quality Gates

### Full Verification Gate (`corepack pnpm verify`)
The repository verification gate ran cleanly with exit code 0:

```
$ corepack pnpm format:check && corepack pnpm lint && corepack pnpm typecheck && corepack pnpm test && corepack pnpm contracts:check && corepack pnpm build
$ uv run ruff format --check . && corepack pnpm --filter @episignal/web exec prettier --check .
187 files already formatted
All matched files use Prettier code style!
$ uv run ruff check . && corepack pnpm --filter @episignal/web lint
All checks passed!
$ next lint
✔ No ESLint warnings or errors
$ uv run mypy packages/backend apps/api && corepack pnpm --filter @episignal/web typecheck
Success: no issues found in 65 source files
$ tsc --noEmit
$ uv run pytest packages/backend/tests apps/api/tests && corepack pnpm --filter @episignal/web test
........................................................................ [  8%]
........................................................................ [ 17%]
........................................................................ [ 26%]
........................................................................ [ 34%]
........................................................................ [ 43%]
........................................................................ [ 52%]
........................................................................ [ 60%]
........................................................................ [ 69%]
........................................................................ [ 78%]
........................................................................ [ 86%]
........................................................................ [ 95%]
.....................................                                    [100%]
829 passed, 1 warning in 10.97s

 RUN  v4.1.11 D:/Projects/Side Project/EpiSignal/apps/web

 ✓ src/lib/api-health.test.ts (2 tests) 27ms
 ✓ src/lib/radar-map-helpers.test.ts (7 tests) 42ms
 ✓ src/lib/api-signals.test.ts (3 tests) 37ms
 ✓ src/lib/api-radar.test.ts (16 tests) 115ms
 ✓ src/lib/api-pipeline.test.ts (13 tests) 66ms
 ✓ src/components/signal-map.test.tsx (4 tests) 728ms
 ✓ src/components/pipeline-monitor.test.tsx (5 tests) 869ms
 ✓ src/components/home-shell.test.tsx (8 tests) 1438ms

 Test Files  8 passed (8)
      Tests  58 passed (58)
   Duration  8.49s

$ uv run python -m episignal_backend.db.verify_contracts
Contracts check passed: Python enums match database constraints and views exactly.
$ corepack pnpm --filter @episignal/web build
$ next build
▲ Next.js 15.5.12
  Creating an optimized production build ...
✓ Compiled successfully in 3.12s
✓ Generating static pages (6/6)
  Finalizing page optimization ...

Route (app)                              Size     First Load JS
┌ ○ /                                    28.7 kB         135 kB
├ ○ /_not-found                          987 B           107 kB
├ ○ /admin/pipeline                      4.01 kB         110 kB
├ ƒ /api/health                          138 B           106 kB
├ ƒ /api/pipeline/runs                   138 B           106 kB
└ ƒ /api/radar                           138 B           106 kB
+ First Load JS shared by all            106 kB
```

### Database Health Check (`corepack pnpm db:check`)
```
database=up postgis=up
```

---

## 4. Browser Verification & UX Observations

1. **Desktop Viewport:**
   - The top masthead provides brand identity, primary navigation links (`Map`, `Signals`, `Pipeline Monitor`, `About`), and live API connectivity badge.
   - The interactive MapLibre map renders at the top with a signal count pill overlay (`0 of 5 signals plotted (5 unresolved coordinates)`).
   - Below the map, signals are rendered in clear evidence cards with source metadata, separate credibility tiers, explicit location badges (`📍 Location unresolved`), and 5-slot briefs.
   - Clicking a card or navigating via keyboard selects the card with high-contrast ring highlighting and synchronizes with the map view.
   - Map markers display an accessible detail popup containing the signal's title, source standing, tier, location precision, extraction confidence, and dual surveillance/evidence scores.

2. **Mobile Viewport:**
   - Responsive single-column layout collapses smoothly to mobile screens (`< 640px`).
   - Map height dynamically adjusts to `h-80` with touch-enabled pan/zoom.
   - Cards stack vertically with large tap targets and legible typography.
   - Marker detail overlay displays cleanly within the mobile viewport without overflowing.

3. **Accessibility & Keyboard Navigation:**
   - Each signal card functions as an accessible control with `tabIndex={0}`, `role="button"`, and `aria-pressed`.
   - Pressing `Enter` or `Space` selects the card.
   - External source links (`<a>`) use `e.stopPropagation()` so opening the original source does not trigger card selection or conflict with navigation.

4. **Map Error Fallback:**
   - When MapLibre WebGL or tile services fail, a non-blocking fallback banner is rendered: `"Map unavailable. All signals remain accessible in the list below."`
   - The signal list below remains 100% interactive and accessible.

---

## 5. Live Proof

### Live Coherent Radar Signal (`hours=168, limit=10`)
Querying the live PostgreSQL database:
- **Total matching items in 168h window:** 5
- **Coherent Evidence Signal:**
  - **ID:** `ec1cac1f-078a-45fe-8524-dacfa863c74c`
  - **English Title:** At least 50 children dead from diphtheria outbreak in Northwest Nigeria
  - **Source Name:** `Antara News`
  - **Source URL:** `https://en.antaranews.com/news/376241/at-least-50-children-dead-from-diphtheria-outbreak-in-northwest-nigeria`
  - **Source Standing:** `is_official: false`, `credibility_tier: "unknown"` (Rendered as: `Media Source`, `Tier: unknown`)
  - **Location:** `None` (Rendered as: `📍 Location unresolved`)
  - **Extraction Confidence:** 0.90 (90%)
  - **Event Context Status:** `none` (`event: null`)
  - **5-Slot Brief:**
    1. `[what_where]` (reported: true): Diphtheria outbreak in Kano State, Northwest Nigeria, affecting communities like Ridin and Sabuwar Kaura.
    2. `[counts]` (reported: true): 50 children have died, with about 100 individuals currently receiving treatment.
    3. `[timing]` (reported: true): Outbreak occurred as of August 26, 2026.
    4. `[spread]` (reported: true): Cases reported across at least four communities including Ridin, Sabuwar Kaura, Dan Isa, and Tsigi.
    5. `[reporting]` (reported: true): Reported by Antara News citing Xinhua news agency.
  - **Forbidden Key Verification:** Confirmed that `raw_text`, exception tracebacks, model prompts, and internal credentials are absent from the JSON output.

### Discovered Upstream Data Defect: Signal `852aa204-846d-4aa6-a256-82c187fdeaef`
- **Observed State:** Signal row `852aa204-846d-4aa6-a256-82c187fdeaef` in the live database has title `"Pennsylvania reports first 2 measles deaths in the US this year, both people unvaccinated"` and URL `kake.com`, but its `raw_text` contains an 87-character Luanda cholera excerpt.
- **Root Cause Diagnosis:**
  1. In a pre-C2 development pass, an 87-character cholera test string was manually or errantly written into the signal's `raw_text` column without updating the title or recalculating `content_hash`.
  2. The stored `content_hash` (`cc269f8...`) does not match `content_hash(title, raw_text)` (`f87b127...`), proving the row's text was corrupted/swapped post-ingestion.
  3. When C2 extraction ran, `validate_extraction()` checked fact grounding against `raw_text` (which passed for the cholera brief), but did not validate cross-field title-to-body semantic coherence.
- **Resolution Path:** In accordance with instructions, this row was left untouched in the live database. Bounded radar pagination and strict payload parsing ensure that such data defects do not break the radar read model or consume pagination limits while valid lower-ranked rows exist.

### Live Pipeline Run Monitor Query
- **Total pipeline runs recorded:** 2
- **Sample Real Run:**
  - **ID:** `586862cf-aef2-47b9-9c3f-2000abacc5ee`
  - **Chain:** `daily`
  - **Trigger:** `manual`
  - **Status:** `failed`
  - **Is Stale:** `false`
  - **Failures:** `[{"stage": "extract", "error": null}]`
  - **Counts:** Serialized safely as counts-only integers.

---

## 6. Conclusion & Next Steps

Sub-Project E is complete, fully tested, and verified against all quality, accessibility, and domain safety invariants. The Signal Radar and Pipeline Monitor provide robust early-warning intelligence and transparent operational oversight.

The implementation is ready for handoff to the planner.
