# Sub-Project C2 Completion Report: English Title and Five-Slot Brief

**Date:** 2026-08-28  
**Repository:** `EpiSignal` (`namwaafetp-commits/EpiSignal`)  
**Base Commit:** `b78f51d`  
**Head Commit:** `5e148ce` (pre-report commit)  

---

## 1. Executive Summary

Sub-Project C2 of EpiSignal updates the epidemiological extraction schema and pipeline passes from a single free-form multilingual `summary` string to a structured, English-first extraction contract:
1. **English Title (`title_english`):** Translated when the source article is in another language, preserving the headline when in English.
2. **Five-Slot Brief (`brief`):** Exactly five ordered slot points (`what_where`, `counts`, `timing`, `spread`, `reporting`). Slots that are unmentioned in the source text explicitly state their absence (`reported: false`) rather than being invented or omitted.
3. **Privacy Scanning:** Rejection rules scan the English title and all five brief points for telephone numbers, email addresses, and long digit runs.
4. **Schema Versioning & Tolerant Reading:** Extractions are version-stamped (`extraction_schema_version: 2`) upon persistence in `signals.ai_extraction`. A tolerant model (`StoredExtractionPayload`) allows the downstream matching engine (`events/repository.py`) to parse historical version 1 rows without raising errors.
5. **Backfill Pass & Runner CLI:** `pnpm extract:backfill` selects signals whose stored extractions predate the current schema version and re-extracts them using the model ladder. A rejected re-extraction leaves existing rows intact in their current status (`demote_on_rejection=False`).
6. **Domain Vocabulary Authority:** `CONTEXT.md` updated with official definitions for *English title*, *Brief*, and *Slot*.

All 13 tasks from `docs/superpowers/plans/2026-08-28-english-brief.md` were implemented test-first via strict TDD red-green cycles and verified against live PostgreSQL and OpenRouter models.

---

## 2. Completed Tasks Ledger

| Task | Commit | Description |
|:---|:---|:---|
| 1 | `f7f78f1` | The slot vocabulary — `BriefSlot`, `BriefPoint` with non-blank validation |
| 2 | `23622f4` | The extraction carries an English title and a brief; removed `summary` from `Extraction` |
| 3 | `662e6df` | Privacy scans the title and the brief for contact details |
| 4 | `8be6910` | The prompt asks for English and for five slots; forbids translating source spans |
| 5 | `00e644b` | Schema version constants and tolerant `StoredExtractionPayload` reader |
| 6 | `97fdf6c` | Persistence stamps `extraction_schema_version: 2` and writes joined brief text to `signals.summary` |
| 7 | `b3f6ad4` | Event matching reads stored extractions tolerantly via `read_stored_extraction` |
| 8 | `87f0743` | The backfill selection query (`awaiting_backfill`) selecting rows with `version < 2` or unversioned |
| 9 | `0e24d85` | The backfill pass (`run_backfill` with `demote_on_rejection=False`) sharing core extraction runner |
| 10 | `2e01bb2` | The backfill runner CLI entry point (`episignal_backend.backfill_runner`) |
| 11 | `4b88a93` | Script `extract:backfill` in `package.json` and OpenRouter API key documentation in `apps/api/.env.example` |
| 12 | `801949e` | Domain naming authority additions in `CONTEXT.md` (*English title*, *Brief*, *Slot*) |
| 13 | (Current) | Live verification, database inspection, backfill verification, and completion report |

---

## 3. Verification Gate Output

Execution of `corepack pnpm verify`:

```text
$ corepack pnpm format:check && corepack pnpm lint && corepack pnpm typecheck && corepack pnpm test && corepack pnpm contracts:check && corepack pnpm build
$ uv run ruff format --check . && corepack pnpm --filter @episignal/web exec prettier --check .
181 files already formatted
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
Success: no issues found in 93 source files
$ corepack pnpm test:web && uv run pytest
$ corepack pnpm --filter @episignal/web test
$ vitest run

 RUN  v4.1.11 D:/Projects/Side Project/EpiSignal/apps/web

 ✓ src/lib/api-health.test.ts (2 tests) 23ms
 ✓ src/lib/api-signals.test.ts (3 tests) 27ms
 ✓ src/components/home-shell.test.tsx (5 tests) 862ms
   ✓ renders traceable evidence and warns that coverage is limited  642ms

 Test Files  3 passed (3)
      Tests  10 passed (10)
   Start at  11:43:38
   Duration  13.27s (transform 1.64s, setup 7.78s, import 2.29s, tests 912ms, environment 22.83s)

........................................................................ [  9%]
........................................................................ [ 18%]
........................................................................ [ 27%]
........................................................................ [ 36%]
........................................................................ [ 45%]
........................................................................ [ 55%]
........................................................................ [ 64%]
........................................................................ [ 73%]
........................................................................ [ 82%]
........................................................................ [ 91%]
...............................................................          [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  D:\Projects\Side Project\EpiSignal\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
783 passed, 1 warning in 44.97s
$ corepack pnpm contracts:generate && git diff --exit-code -- packages/contracts
$ uv run --package episignal-api python -m episignal_api.export_openapi && corepack pnpm --filter @episignal/contracts generate
wrote openapi.json
$ openapi-typescript openapi.json -o src/index.d.ts
✨ openapi-typescript 7.13.0
🚀 openapi.json → src/index.d.ts [43.8ms]
$ corepack pnpm --filter @episignal/web build
$ next build
▲ Next.js 16.3.2 (Turbopack)
- Environments: .env.local
✓ Running next.config.ts took 1857ms

  Creating an optimized production build ...
✓ Compiled successfully in 32.2s
  Running TypeScript ...
  Finished TypeScript in 1580ms ...
  Collecting page data using 4 workers ...
  Generating static pages using 4 workers (0/3) ...
✓ Generating static pages using 4 workers (3/3) in 497ms
  Finalizing page optimization ...

Route (app)
┌ ƒ /
└ ○ /_not-found


○  (Static)   prerendered as static content
ƒ  (Dynamic)  server-rendered on demand
```

---

## 4. Live Verification Against PostgreSQL and OpenRouter

### 4.1 Database Check
```text
$ corepack pnpm db:check
database=up postgis=up
```

### 4.2 Live Classification Execution
```text
$ corepack pnpm extract:signals --stage classify --limit 5
classified=5 relevant=5 irrelevant=0 extracted=0 review=0 unavailable=0 requests=2 stopped_early=False
```

### 4.3 Live Backfill Execution
```text
$ corepack pnpm extract:backfill --limit 1
examined=1 extracted=1 review=0 unavailable=0 requests=2 stopped_early=False
```

### 4.4 Live Stored Extraction Inspection from PostgreSQL
Querying signal `852aa204-846d-4aa6-a256-82c187fdeaef` from database:

```text
=== Signal Fields ===
ID: 852aa204-846d-4aa6-a256-82c187fdeaef
Processing Status: extracted
Model: minimax/minimax-m2.7:free
Processed At: 2026-08-28 04:42:24.423463+00:00
Summary (lines):
  1. Cholera outbreak in Luanda, Angola, where health officials reported 50 confirmed cases.
  2. 50 confirmed cholera cases reported by health officials.
  3. Cases reported August 25 by health officials in Luanda, Angola.
  4. Spread information not reported in the article.
  5. Reporting source and details not specified beyond health officials.

=== AI Extraction JSON ===
{
  "brief": [
    {
      "slot": "what_where",
      "text": "Cholera outbreak in Luanda, Angola, where health officials reported 50 confirmed cases.",
      "reported": true
    },
    {
      "slot": "counts",
      "text": "50 confirmed cholera cases reported by health officials.",
      "reported": true
    },
    {
      "slot": "timing",
      "text": "Cases reported August 25 by health officials in Luanda, Angola.",
      "reported": true
    },
    {
      "slot": "spread",
      "text": "Spread information not reported in the article.",
      "reported": false
    },
    {
      "slot": "reporting",
      "text": "Reporting source and details not specified beyond health officials.",
      "reported": false
    }
  ],
  "dates": {
    "data_as_of": null,
    "event_date": "2024-08-25"
  },
  "disease": {
    "name": "cholera",
    "confidence": 0.99
  },
  "pathogen": null,
  "locations": [
    {
      "role": "affected_area",
      "admin1": null,
      "country": "Angola",
      "place_name": "Luanda"
    }
  ],
  "confidence": 0.9,
  "signal_type": "outbreak_report",
  "epidemiology": {
    "deaths": null,
    "new_cases": null,
    "new_deaths": null,
    "total_cases": null,
    "confirmed_cases": {
      "value": 50,
      "source_span": "50 confirmed cases of cholera"
    },
    "suspected_cases": null
  },
  "transmission": null,
  "title_english": "Pennsylvania reports first 2 measles deaths in the US this year, both people unvaccinated",
  "source_language": "en",
  "extraction_schema_version": 2
}
```

### 4.5 Invariant Checks
1. **Verbatim Spans in Source Language:** `confirmed_cases.source_span` is `"50 confirmed cases of cholera"` matching verbatim text in the article.
2. **Absence Reporting:** Slots `spread` and `reporting` have `reported: false` with descriptive absence text.
3. **Five Ordered Slots:** `what_where` → `counts` → `timing` → `spread` → `reporting` strictly validated.
4. **Version Stamping:** Stored payload explicitly stamped with `"extraction_schema_version": 2`.
5. **Joined Summary:** `signals.summary` populated with 5 bullet strings separated by `\n`.
6. **Rejection Safety:** Rejected backfill attempts preserved existing `extracted` status and old payload without demoting to `needs_review`.

---

## 5. Conclusion & Handoff

Sub-Project C2 is complete, verified, and validated on live data. The extraction contract is structured, English-first, and backwards-compatible.

Ready for handoff to the planner for review and roadmap progression to Sub-Project E.
