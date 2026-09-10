# GDELT Web Legacy NGram benchmark

**Date:** 2026-09-10 UTC
**Branch:** `codex/next-iteration`
**Previous HEAD:** `cff830a85067e2648be4c8baab2b6a1a603dd2f2`

## Implementation

Files changed:

- `packages/backend/scripts/benchmark_gdelt_ngrams.py`
- `packages/backend/scripts/__init__.py`
- `packages/backend/tests/test_benchmark_gdelt_ngrams.py`
- `benchmarks/results/2026-09-10-gdelt-ngrams-benchmark.txt`

The script is developer-only code under `packages/backend/scripts/`. No
scheduled runner imports or invokes it. It does not use the GDELT DOC API,
AI providers, publisher article bodies, the database, or production settings.

Rules reuse `episignal_backend.seeds.load_query_rules()`, retaining active
English query rules and stripping only the seed's display quotes. Matching is
case-insensitive token matching, so single-word rules do not match substrings;
multi-word rules match contiguous quadgram tokens. Matching labels are retained
through DOCID joins and URL deduplication.

Each batch downloads compressed NGram and TOC files into one OS temporary
directory. NGrams are streamed through gzip, only matched DOCIDs are retained,
the NGram file is deleted, and the TOC is then streamed and deleted. Temporary
storage is measured as the larger compressed file, and cleanup is owned by a
context manager. Missing files are normal during backward scanning. Hard limits
are eight batches, six hours, bounded request timeout, and one batch at a time.

## Live benchmark

Command:

```text
uv run --package episignal-backend python packages/backend/scripts/benchmark_gdelt_ngrams.py --recent-hours 2 --max-batches 4 --timeout-seconds 10 --output benchmarks/results/2026-09-10-gdelt-ngrams-benchmark.txt
```

Time window: two hours UTC, five-minute safety lag. 4 available pairs were
processed: `2026-09-10T10:02Z`, `10:01Z`, `09:47Z`, and `09:46Z`.

Bandwidth:

- Total: **43.125 MB**
- Average: **10.781 MB/batch**
- Estimated: **21.562 MB/hour**, **0.517 GB/day**, **15.525 GB/30-day month**
- Projected VPS total: **46.525 GB/month** = 31 GB baseline + 15.525 GB NGram
- Baseline remains an approximate whole-VPS interface counter, not EpiSignal-only billing data.

Performance:

- Total elapsed: **193.75 seconds**
- Download: **14.58 seconds**
- NGram scan: **170.85 seconds**
- TOC processing: **0.42 seconds**
- Peak RAM: **79.4 MB**
- Peak temporary disk: **16.589 MB**

Yield:

- Documents represented: **10,632**
- Matched DOCIDs: **32**
- Candidate URLs: **32**
- Unique candidate URLs: **32**
- Download per unique candidate: **1.348 MB**

Top matching rules: Dengue 10, MERS 8, Chikungunya 6, Zika 5, Salmonella 3.
Top languages: English 13, Romanian 6, French 3, Spanish 3, Italian 2.
Top domains: `www.kudika.ro` 3, `www.prnewswire.com` 2, `www.ellitoral.com` 2.

Up to 30 safe examples, with title and URL but no body, are in the committed
benchmark output file.

## Assessment

- **Bandwidth:** Feasible at this sample rate, adding about 15.5 GB/month to the stated VPS baseline. More samples are needed before treating this as a stable planning number.
- **CPU:** Main cost is Python token scanning: 170.85 seconds for 43.125 MB. This is acceptable for a bounded PoC but needs profiling or a faster matcher before production use.
- **RAM:** 79.4 MB peak observed.
- **Disk:** 16.589 MB peak compressed temporary storage; no historical files were retained.
- **Candidate yield:** 32 URLs from 10,632 represented documents. Manual review shows useful disease-related headlines mixed with obvious lexical false positives, such as biography, weather, historical, and unrelated pages. NGram matching is discovery only and does not establish relevance.
- **Limitations:** Four batches are a small point sample; batch availability was sparse within the two-hour horizon; no publisher body retrieval or downstream filter was tested; candidate quality may vary by time, language, and source mix.

## Verification

Focused benchmark tests: **9 passed**.
Web tests: **125 passed in 15 files**.
Python tests: **1,480 passed, 2 skipped**, 2 existing dependency deprecation warnings.
Format: **PASS** — 312 Python files formatted; Prettier passed.
Lint: **PASS** — ESLint and Ruff passed.
Typecheck: **PASS** — TypeScript passed; mypy reported no issues in 147 source files.
Contracts: **PASS** — OpenAPI generation and contract generation passed with no content diff.
Build: **PASS** — Next.js production build completed.
Alembic head: **`20260908_0023`**, unchanged.

The first full verification attempt hit one transient web test timeout in
`admin-review-queue.test.tsx`; the focused file rerun passed 6/6, and the second
full `corepack pnpm verify` passed.

## Git and production boundary

Branch: `codex/next-iteration`
New commit: recorded after report commit
Local HEAD: recorded after commit
Remote HEAD: recorded after push
Working tree: clean after push

- Deployed: **NO**
- Production pipeline changed: **NO**
- Cron changed: **NO**
- Environment changed: **NO**
- Database changed: **NO**
- VPS accessed: **NO**
- Coolify accessed: **NO**
