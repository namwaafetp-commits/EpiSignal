# Production GDELT NGram discovery report

Date: 2026-09-11
Branch: `codex/next-iteration`
Commit verified: `0b4019b`

## IMPLEMENTATION

Production connector:

- Added `GdeltNgramClient` and `GdeltNgramDiscovery` under the production GDELT ingestion package.
- Inventory accepts only complete NGram/TOC pairs, downloads one pair at a time, streams gzip contents, matches active query rules, resolves DOCIDs through TOC, enforces rule language, canonicalizes and deduplicates URLs, and removes temporary files.
- Scheduled discovery uses active database query rules and the existing discovery/article contracts.

Cursor/state:

- Added `gdelt_discovery_state`, keyed by provider, with a nullable batch cursor and update timestamp.
- Cursor writes happen in the same session as stored candidates and only after successful batch processing and storage.
- Failed batches remain retryable. Restart and redeploy reuse the durable cursor. Telegram SQLite state is not used.

Catch-up:

- Safe publication lag is five minutes.
- Catch-up is bounded to six hours by default and capped by maximum batch count.
- A cursor older than the bound processes only the recent bounded window; the resulting cursor and metrics expose the gap.

Failure handling:

- Reports `healthy`, `partial_degradation`, and `unavailable` provider states.
- Partial runs retain candidates from successful batches and expose failed-batch counters.
- Total provider failure makes discovery unhealthy and returns a non-zero standalone exit status.
- Healthy zero-candidate runs remain healthy only after at least one batch succeeds.

## REVIEW CORRECTIONS

The focused production review identified and corrected three continuity and
health-reporting defects without changing the pipeline shape:

- A persisted NGram cursor is now authoritative over a newer generic scheduler
  window start, while the six-hour catch-up floor remains in force.
- Inventory scans the complete bounded window and returns chronological pairs;
  the discovery cap is applied after the persisted cursor is filtered, so older
  unprocessed batches are handled before newer ones and a mid-stream failure
  cannot be skipped.
- A run is healthy only after at least one complete batch succeeds. Zero
  complete pairs and all-failed runs are unavailable; successful zero-news runs
  remain healthy.

Resource safeguards:

- One batch at a time.
- Streaming gzip reads.
- Temporary directory cleanup on success and failure.
- Bounded HTTP timeout, 64-batch default maximum, six-hour default catch-up, and 1.5 GB per-run download budget.

DOC API behavior:

- `GdeltDocClient` remains in the codebase for explicit retrieval/developer use.
- Scheduled discovery constructs only the NGram client. It does not automatically fall back to DOC API after NGram failure.

## PIPELINE

old:

```text
DOC API → downstream
```

new:

```text
NGram → downstream
```

Downstream article deduplication, DeepSeek relevance and host-sector classification, retrieval, Gemini, normalization/grouping, event matching, and Mistral behavior remain unchanged.

## METRICS

Discovery emits:

`minutes_checked`, `ngram_files_seen`, `toc_files_seen`, `complete_pairs`, `batches_attempted`, `batches_succeeded`, `batches_failed`, `bytes_downloaded`, `documents_scanned`, `raw_matched_docids`, `language_filtered_candidates`, `unique_candidates`, `catchup_minutes`, `cursor_before`, `cursor_after`, and `provider_status`.

## TESTS

NGram-specific:

- Production NGram tests cover inventory, incomplete pairs, gzip streaming, active rule matching, English filtering, French `MERS` regression, multiple rules per DOCID, URL deduplication, cursor behavior, bounded catch-up, partial/total failure, normal pipeline handoff, and cleanup.
- Review-correction regressions cover durable-cursor precedence, three-run
  oldest-first batch continuity under `max_batches`, mid-batch failure
  continuity, and zero-candidate health semantics.
- Benchmark tests cover the standalone benchmark logic and unwritable optional output behavior.

Python: 1,501 passed, 2 skipped, 2 existing warnings.
Web: 125 passed.
format: PASS.
lint: PASS.
typecheck: PASS; mypy checked 148 source files.
contracts: PASS.
build: PASS.
Alembic: migration `20260911_0024_gdelt_ngram_state` added and migration-head/model allowlist checks pass. No production database was accessed.

## REVIEW RISKS

1. The migration must be applied before scheduled NGram discovery runs against a database that lacks `gdelt_discovery_state`.
2. GDELT batch publication and HEAD availability remain external dependencies; provider status is intentionally visible when they fail.
3. When the normal article cap is exceeded, cursor advancement waits until deferred candidates are stored on a later idempotent run.

## GIT

Previous implementation HEAD: `ed6cfef`.
Correction commit: `0b4019b`.
The full verification gate ran against the correction tree; this report and
the status-ledger update are documentation follow-up.

## PRODUCTION

Deployed: NO
Cron changed: NO
Environment changed: NO
Production DB accessed: NO
VPS accessed: NO
Coolify accessed: NO
