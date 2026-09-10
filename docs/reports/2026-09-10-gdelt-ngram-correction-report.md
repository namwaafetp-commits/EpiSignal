# GDELT Web Legacy NGram benchmark correction

**Date:** 2026-09-10 UTC  
**Branch:** `codex/next-iteration`  
**Previous HEAD:** `40ce88d8e41f0c308ed6905d90be6bfa8d62b0f2`

## Corrections

### Complete batch-density method

`--all-batches` now inspects every minute in a bounded two-hour window, probes
NGram and TOC availability independently, records each file count, and only
processes timestamps where both files are present. Capped mode is explicitly
marked as a sample and returns no full-window bandwidth extrapolation. Discovery
probes are concurrent but rate-limited and retry transient responses; file
downloads remain one batch at a time in disposable temporary storage.

### Language filtering

The benchmark loads only active English rules, reports raw lexical DOCID and
candidate counts for diagnostics, and applies the production-equivalent
`lang == "en"` TOC guard before all production yield and efficiency metrics.
The French `mers` regression is covered: it remains a raw lexical match but is
not an English candidate for the `MERS` rule.

### URL canonicalization

Candidate deduplication now calls the production
`episignal_backend.ingestion.urls.canonicalize_url` utility. Tracking
parameters, fragments, host casing, trailing slashes, and meaningful query
parameter ordering therefore follow the existing discovery contract.

## Two-hour live benchmark

Command:

```text
uv run --package episignal-backend python packages/backend/scripts/benchmark_gdelt_ngrams.py --as-of 2026-09-10T10:12:00Z --recent-hours 2 --all-batches --timeout-seconds 10 --output benchmarks/results/2026-09-10-gdelt-ngrams-corrected-benchmark.txt
```

Window: **2026-09-10 08:07–10:07 UTC**, with the five-minute safety lag. The
exhaustive inventory checked **121 minutes**, found **2 NGram files**, **0 TOC
files**, and therefore **0 complete pairs** and **0 processed batches**.

This is reported as unavailable evidence, not zero traffic. A direct HEAD
probe for a known historical NGram and TOC URL returned 200, but a direct GET
of the known NGram file timed out during the bounded 60-second transfer test.
The source was not reliable enough to claim a corrected full-window bandwidth
rate or live resource envelope.

| Metric | Corrected live result |
| --- | ---: |
| NGram MB | unavailable |
| TOC MB | unavailable |
| Total MB | unavailable |
| MB/hour | unavailable |
| GB/day | unavailable |
| GB/30-day month | unavailable |
| Projected VPS GB/month | unavailable; baseline is approximately 31 GB/month |
| Documents represented | unavailable |
| Raw lexical DOCIDs | unavailable |
| English DOCIDs | unavailable |
| English unique candidate URLs | unavailable |
| MB/English candidate | unavailable |

## Matcher profile

The old and new matchers were run against the same 100,000-row local fixture
using the active English rules:

- Old matcher scan: **0.39 seconds**
- New cached matcher scan: **0.19 seconds**
- Speedup: **2.09x**
- Match sets identical: **YES**

The live script now records compressed bytes, uncompressed bytes, rows,
quadgrams, tokenization time, matching time, gzip/decompression time, total
scan time, and both compressed and uncompressed MB/sec when a complete pair is
available. Those live fields are unavailable for this run because no pair was
processed.

## Feasibility

- Bandwidth: **RED** — no complete pair was processable in the corrected window.
- CPU/runtime: **YELLOW** — local matcher profile is improved, but no live NGram scan was available to project hourly workload.
- RAM: **YELLOW** — no corrected live batch completed.
- Disk: **YELLOW** — no corrected live batch completed.
- Candidate discovery: **YELLOW** — lexical discovery still requires downstream relevance filtering even when the source is available.

**Recommendation: OPTIMIZE MORE.** Do not migrate the production discovery
pipeline based on this unavailable live window. The earlier four-batch PoC
resource numbers remain historical context only and are not reused as corrected
full-window estimates.

## Verification

Focused benchmark suite: **13 passed**. Ruff format, Ruff lint, and diff
hygiene passed.

Full `corepack pnpm verify`: **PASS**.

- Python: **1,484 passed, 2 skipped**, 2 existing dependency deprecation warnings
- Web: **125 passed in 15 files**
- Format: **PASS** — Ruff and Prettier
- Lint: **PASS** — Ruff and ESLint
- Typecheck: **PASS** — TypeScript and mypy; 147 Python source files
- Contracts: **PASS** — generated output had no content diff
- Build: **PASS** — Next.js production build
- Alembic: **`20260908_0023`**, unchanged

## Production boundary

- Deployed: **NO**
- Production pipeline changed: **NO**
- Cron changed: **NO**
- Environment changed: **NO**
- Database changed: **NO**
- VPS accessed: **NO**
- Coolify accessed: **NO**

## Git

Implementation commit and final verification commit metadata are recorded in
the task completion summary after push.
