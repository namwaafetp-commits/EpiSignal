# Sub-Project C2 Completion Report: English Title and Five-Slot Brief

**Date:** 2026-08-28
**Repository:** `EpiSignal` (`namwaafetp-commits/EpiSignal`)
**Base Commit:** `b78f51d`
**Initial Completion Head:** `5e148ce`
**Correction Commit Range:** `3ecda02`..`b26e794`
**Verification Gate Commit:** `b26e794`

---

## 1. Executive Summary

Sub-Project C2 of EpiSignal transitions epidemiological extraction from a single free-form multilingual `summary` string to a structured, English-first extraction contract:
1. **English Title (`title_english`):** Stored alongside the publisher's headline, translated to English when the source article is non-English.
2. **Five-Slot Brief (`brief`):** Exactly five ordered slot points (`what_where`, `counts`, `timing`, `spread`, `reporting`). Unmentioned slots explicitly state absence (`reported: false`) rather than being hallucinated or omitted.
3. **Strict Validation & Vocabulary:** Language validation enforces the ISO 639-1 two-letter vocabulary (or null). Privacy scanning rejects contact details in the English title and brief.
4. **Schema Versioning & Tolerant Reading:** Extractions are version-stamped (`extraction_schema_version: 2`) upon persistence in `signals.ai_extraction`. Downstream consumers read stored extractions tolerantly via `StoredExtractionPayload`.
5. **Backfill Pass & Honest Runner Exits:** `pnpm extract:backfill` upgrades pre-v2 signals without demoting existing data on rejection (`demote_on_rejection=False`). Counter accounting reflects only committed transaction outcomes, and the CLI returns non-zero if any signal encounters rejection, unavailability, or storage failure.
6. **Domain Naming Authority:** `CONTEXT.md` updated with normative definitions for *English title*, *Brief*, and *Slot*.

Following planner review of the initial C2 submission, a 5-task correction pass resolved false-success backfill exits, pre-commit outcome counting, syntax-only language code validation, ungrounded fixture phrasing, and incomplete live evidence.

---

## 2. Completed Tasks and Correction Ledger

### Initial Implementation Tasks

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

### Completion Correction Tasks

| Task | Commit | Description |
|:---|:---|:---|
| C1 | `3ecda02` | Count only committed extraction outcomes and expose `storage_failed` in `ExtractionResult` |
| C2 | `740e6f1` | Make backfill command exit with code 1 on rejected, unavailable, or storage-failed signals |
| C3 | `9704271` | Enforce ISO 639-1 vocabulary set for `source_language` validation |
| C4 | `9432eb9` | Make brief fixtures source-backed, removing unsupported attribution and media claims |
| C5 | (Current) | Re-run full verification gate, prove backfill idempotence, and provide coherent live evidence |

---

## 3. Verification Gate Output

Executed at commit `b26e794` (`corepack pnpm verify`):

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
(!) Your Vite config uses features that are unsupported by `configLoader: 'native'`, which is planned to become the default in a future major version of Vite:
  - ESM syntax in a file loaded as CommonJS (vitest.config.ts:1:1). Use a `.mjs` extension or set `"type": "module"` in the closest package.json
Set `VITE_CONFIG_NATIVE_IGNORE_WARNING=true` to suppress this warning.
The plugin "vite-tsconfig-paths" is detected. Vite now supports tsconfig paths resolution natively via the resolve.tsconfigPaths option. You can remove the plugin and set resolve.tsconfigPaths: true in your Vite config instead.

 RUN  v4.1.11 D:/Projects/Side Project/EpiSignal/apps/web

 ✓ src/lib/api-health.test.ts (2 tests) 18ms
 ✓ src/lib/api-signals.test.ts (3 tests) 21ms
 ✓ src/components/home-shell.test.tsx (5 tests) 791ms
   ✓ renders traceable evidence and warns that coverage is limited  557ms

 Test Files  3 passed (3)
      Tests  10 passed (10)
   Start at  12:59:42
   Duration  11.74s (transform 1.21s, setup 7.58s, import 1.70s, tests 830ms, environment 19.59s)

........................................................................ [  9%]
........................................................................ [ 18%]
........................................................................ [ 27%]
........................................................................ [ 36%]
........................................................................ [ 45%]
........................................................................ [ 54%]
........................................................................ [ 63%]
........................................................................ [ 73%]
........................................................................ [ 82%]
........................................................................ [ 91%]
.....................................................................    [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  D:\Projects\Side Project\EpiSignal\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
789 passed, 1 warning in 48.98s
$ corepack pnpm contracts:generate && git diff --exit-code -- packages/contracts
$ uv run --package episignal-api python -m episignal_api.export_openapi && corepack pnpm --filter @episignal/contracts generate
wrote openapi.json
$ openapi-typescript openapi.json -o src/index.d.ts
✨ openapi-typescript 7.13.0
🚀 openapi.json → src/index.d.ts [111.3ms]
$ corepack pnpm --filter @episignal/web build
$ next build
▲ Next.js 16.3.2 (Turbopack)
- Environments: .env.local
✓ Running next.config.ts took 1928ms

  Creating an optimized production build ...
✓ Compiled successfully in 74s
  Running TypeScript ...
  Finished TypeScript in 9.1s ...
  Collecting page data using 4 workers ...
  Generating static pages using 4 workers (0/3) ...
✓ Generating static pages using 4 workers (3/3) in 1232ms
  Finalizing page optimization ...

Route (app)
┌ ƒ /
└ ○ /_not-found


○  (Static)   prerendered as static content
ƒ  (Dynamic)  server-rendered on demand
```

Exit code: `0`.

---

## 4. Live Database and Pipeline Verification

### 4.1 Database Check
```text
$ corepack pnpm db:check
database=up postgis=up
```

### 4.2 Live Extraction Pass Execution
Full-stage extraction command executed against live signals:

```text
$ corepack pnpm extract:signals -- --limit 10
classified=10 relevant=7 irrelevant=3 extracted=4 review=3 unavailable=0 requests=17 stopped_early=False
```

Correction verification used `--limit 10` rather than the planned limit of 5 to process the already-classified bounded queue in one run. The command remained within configured request and cost guards. No additional paid run was performed.

### 4.3 Backfill Execution Chronology and Idempotence

1. **Initial Backfill Pass (pre-correction run):**
   ```text
   $ corepack pnpm extract:backfill --limit 1
   examined=1 extracted=1 review=0 unavailable=0 requests=2 stopped_early=False
   ```
2. **Idempotence Re-run (during correction verification):**
   ```text
   $ corepack pnpm extract:backfill -- --limit 10
   examined=0 re_extracted=0 rejected=0 unavailable=0 storage_failed=0 requests=0 stopped_early=False
   ```
   The second run confirms idempotence: all eligible historical rows were already upgraded to `extraction_schema_version: 2`, resulting in 0 candidates examined.

### 4.4 Coherent Live Extraction Evidence from PostgreSQL

Signal `ec1cac1f-078a-45fe-8524-dacfa863c74c` was extracted during the live pass:

- **Signal ID:** `ec1cac1f-078a-45fe-8524-dacfa863c74c`
- **Publisher Title:** `Sedikitnya 50 anak tewas akibat wabah difteri di Nigeria Barat Laut`
- **Canonical URL:** `https://www.antaranews.com/berita/5711193/sedikitnya-50-anak-tewas-akibat-wabah-difteri-di-nigeria-barat-laut`
- **AI Model:** `deepseek/deepseek-chat`
- **Processed At:** `2026-08-28 06:42:44.533873+00:00`
- **Source Language:** `id` (Indonesian — valid ISO 639-1 code)
- **English Title:** `At least 50 children dead from diphtheria outbreak in Northwest Nigeria`
- **Disease Name:** `Diphtheria` (confidence 0.95)
- **Schema Version:** `2`
- **Raw Text Prefix (Indonesian):** `Abuja (ANTARA) - Setidaknya 50 anak tewas dan beberapa lainnya dirawat di rumah sakit akibat wabah difteri di negara bagian Kano, Nigeria barat laut, kata badan legislatif negara bagian tersebut pada hari Selasa...`
- **Grounded Span:** `deaths.value = 50`, `source_span = "Setidaknya 50 anak tewas"` (verbatim in source text)

**Stored Five-Slot Brief (`signals.summary`):**
```text
1. Diphtheria outbreak in Kano State, Northwest Nigeria, affecting communities like Ridin and Sabuwar Kaura.
2. At least 50 children dead and several others hospitalized.
3. The outbreak was reported on Tuesday, but the timeline of cases is not mentioned.
4. The outbreak has spread to other communities and towns in six local government areas: Rano, Tudun Wada, Kibiya, Bunkure, Bebeji, and Kiru.
5. Reported by the Kano State House of Assembly, urging emergency actions.
```

**Stored `ai_extraction` JSON Structure:**
```json
{
  "brief": [
    {
      "slot": "what_where",
      "text": "Diphtheria outbreak in Kano State, Northwest Nigeria, affecting communities like Ridin and Sabuwar Kaura.",
      "reported": true
    },
    {
      "slot": "counts",
      "text": "At least 50 children dead and several others hospitalized.",
      "reported": true
    },
    {
      "slot": "timing",
      "text": "The outbreak was reported on Tuesday, but the timeline of cases is not mentioned.",
      "reported": false
    },
    {
      "slot": "spread",
      "text": "The outbreak has spread to other communities and towns in six local government areas: Rano, Tudun Wada, Kibiya, Bunkure, Bebeji, and Kiru.",
      "reported": true
    },
    {
      "slot": "reporting",
      "text": "Reported by the Kano State House of Assembly, urging emergency actions.",
      "reported": true
    }
  ],
  "dates": {
    "data_as_of": null,
    "event_date": null
  },
  "disease": {
    "name": "Diphtheria",
    "confidence": 0.95
  },
  "pathogen": {
    "name": "Corynebacterium diphtheriae",
    "confidence": 0.9
  },
  "locations": [
    {
      "role": "primary",
      "admin1": "Kano",
      "country": "Nigeria",
      "place_name": null
    }
  ],
  "confidence": 0.95,
  "signal_type": "outbreak_report",
  "epidemiology": {
    "deaths": {
      "value": 50,
      "source_span": "Setidaknya 50 anak tewas"
    },
    "new_cases": null,
    "new_deaths": null,
    "total_cases": null,
    "confirmed_cases": null,
    "suspected_cases": null
  },
  "transmission": null,
  "title_english": "At least 50 children dead from diphtheria outbreak in Northwest Nigeria",
  "source_language": "id",
  "extraction_schema_version": 2
}
```

### 4.5 Provenance Clarification and Exclusion of Inconsistent Row

The previous draft report referenced row `852aa204-846d-4aa6-a256-82c187fdeaef` (displaying a Pennsylvania measles publisher title alongside an Angola cholera body from an early pipeline test). That row has been explicitly excluded from acceptance evidence. The primary acceptance evidence is signal `ec1cac1f-078a-45fe-8524-dacfa863c74c` above, whose publisher title, URL, body, English title, disease, and brief describe the identical Indonesian diphtheria outbreak.

---

## 5. Invariants and Security Verification

1. **Source Span Grounding in Native Language:** Spans are checked verbatim against raw article text in the original language without translation (`_check_span` uses case-folded whitespace normalization).
2. **Explicit Absence in Briefs:** Slots not covered in the source article are marked `reported: false` with descriptive absence prose (e.g. slot `timing` above).
3. **Five Ordered Slots:** Strict sequence (`what_where` → `counts` → `timing` → `spread` → `reporting`) validated at ingest and stored in order.
4. **Committed Counter Accounting:** Outcome counts (`extracted`, `reviewed`, `storage_failed`) increment only after database transaction commit succeeds.
5. **Backfill Failure Visibility:** Backfill command returns exit code `1` whenever any signal fails or provider errors occur.
6. **ISO 639-1 Validation:** Two-letter language codes validated against the 184-code ISO 639-1 set.

---

## 6. Known Risks and Observations

- **Upstream Deprecation Warning:** `StarletteDeprecationWarning` from `fastapi.testclient` remains expected and is tracked upstream.
- **Model Endpoint Availability:** OpenRouter free tier model queues (`nemotron:free`, `gemma:free`) experience high variable latency and rate limits. Production deployments require stable paid model tiers (`deepseek/deepseek-chat`, `mistralai/mistral-small-24b-instruct-2501`, `anthropic/claude-3-haiku`).

---

## 7. Next Action

Ready for planner re-review; the worker has not changed ROADMAP.md or HANDOFF.md.
