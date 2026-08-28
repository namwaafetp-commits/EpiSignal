# Report: Signal Content Integrity Guard and Remediation of Corrupted Row 852aa204

**Date:** 2026-08-28
**Repository:** `EpiSignal` (`namwaafetp-commits/EpiSignal`)
**Branch:** `fix/signal-content-integrity` (worktree `.worktrees/signal-integrity`)
**Base Commit:** `6792c1e`
**Verification Gate:** `corepack pnpm verify` (exit code 0), `corepack pnpm db:check` (`database=up postgis=up`)

---

## 1. Executive Summary

This report documents the implementation of content hash integrity verification across the EpiSignal read and extraction pipelines, the remediation of corrupted signal row `852aa204-846d-4aa6-a256-82c187fdeaef`, and subsequent hardening to prevent batch limit shortchanging, break potential pipeline stall loops, provide server-side audit observability, and empirically measure wire transfer costs.

During Sub-Project E verification, signal `852aa204-846d-4aa6-a256-82c187fdeaef` was discovered with a Pennsylvania measles title and an 87-character Luanda cholera body text. The stored `content_hash` was `cc269f81...`, whereas `content_hash(title, raw_text)` computed to `f87b127a...`, demonstrating that the body text had been swapped post-ingestion by a pre-C2 test fixture.

To prevent any corrupted or mismatched signal from being silently served or processed, a multi-layer integrity guard was introduced, backed by rigorous TDD. Furthermore, signal `852aa204-846d-4aa6-a256-82c187fdeaef` was formally quarantined via an Alembic migration (`20260828_0009_quarantine_corrupted_signal`), preserving all original data and diagnostic evidence unmutated.

---

## 2. Task 1 — Content Integrity Guard Design, Enforcement & Observability

### 2.1 Pure Verification Function
`verify_content_hash(title: str, body: str | None, stored_hash: str | None) -> bool` was implemented in `episignal_backend.ingestion.fingerprint`.
- Recomputes `content_hash(title, body or "")` using Unicode NFC normalization and SHA-256 over `title + "\x1f" + body`.
- Rejects empty, non-string, or mismatched stored hashes.
- Gracefully handles `None` body text (equivalent to `""`).

### 2.2 Enforcement Points & Bounded Scan Execution
Integrity enforcement is placed at two critical boundaries:

1. **Radar Read Model (`episignal_backend.radar.query_radar`):**
   - Base query selects `Signal.title`, `Signal.raw_text`, and `Signal.content_hash`.
   - Bounded chunk pagination (`chunk_size = max(limit, 20)`, `max_scan = max(limit * 5, 100)`) scans candidate rows in chunks, evaluating `verify_content_hash`.
   - When a row fails verification, `logger.warning("Signal %s failed content hash integrity check; omitted from radar feed", row.id)` is emitted.
   - **Justification for Omission vs Erroring:** A corrupted row fails the eligibility condition for public radar membership. Erroring out the entire feed would enable a single bad row to cause a Denial of Service for all radar users. Returning the row with an integrity flag would expose contradictory or hallucinated briefs to end users. Omitting the row while logging internally for administrative awareness is the correct domain decision.
   - The chunked scan advances past corrupted rows without consuming or shortchanging the requested page `limit`.

2. **AI Extraction & Classification Pipeline (`episignal_backend.ai.repository.SqlAlchemyAiRepository`):**
   - In `awaiting_classification`, `awaiting_extraction`, and `awaiting_backfill`, candidate signals are fetched using a unified bounded chunk scanner `_scan_valid_signals(base_stmt, limit, pass_name)`.
   - Signals with corrupted content hashes are omitted from the batch and emit `logger.warning("Signal %s failed content hash integrity check; omitted from %s pass", row.id, pass_name)`.
   - `_scan_valid_signals` is typed `base_stmt: Select[tuple[Signal]]` and calls `self._session.execute(chunk_stmt).scalars().all()` directly. An earlier revision typed the parameter `Any` and guarded the call with `hasattr(..., "scalars")` / `hasattr(..., "all")`; those branches existed only to accommodate the `FakeSession`/`FakeResult` test doubles and were unreachable in production. The doubles now expose a `FakeScalarResult` that matches SQLAlchemy's `ScalarResult` interface instead, so the production path is no longer shaped around the tests.
   - **Breaking the Pipeline Stall Loop:** If a corrupted row sits at the head of `order_by(Signal.first_seen_at)`, a naive fixed-limit query with post-filtering would repeatedly fetch the same corrupted row, return fewer items than requested, and permanently stall throughput if `limit` corrupted rows accumulate. The bounded chunk scanner reads ahead up to `max_scan` (e.g. 100 rows), skipping corrupted entries and returning the full requested `limit` of valid signals. As valid signals are processed and their status advances, subsequent batches continue to scan ahead past the corrupted row.
   - **Known limit of this mitigation:** `max_scan` is a ceiling, not an elimination. If more than `max_scan` corrupted rows accumulate ahead of the valid ones in `first_seen_at` order, the scan budget is exhausted before `limit` valid rows are found and throughput degrades again. The scan is deliberately bounded so that a heavily corrupted table cannot turn one batch call into an unbounded table read; the `logger.warning` emitted per skipped row is the intended signal that this threshold is being approached. Note also that each call re-scans from offset 0, so a persistent corrupted row is re-logged on every batch.

### 2.3 Server-Side Observability vs API Boundaries
- Internal warnings containing the offending `signal.id` are written to standard backend logger streams (`logger.warning`).
- Crucially, internal signals, hashes, and article text never cross the API boundary. The external error sanitization regex (`^[A-Za-z_][A-Za-z0-9_]{0,63}$`) established in Sub-Project E remains strictly intact.

### 2.4 Read-Path Performance & Wire Transfer Measurement
Selecting `Signal.raw_text` in `query_radar` requires transferring article bodies across the database connection. To measure real-world cost beyond CPU hashing:

1. **Database Payload Sizes:**
   - Evaluated across live signals in database:
     - Mean `raw_text` size: **1,475.2 bytes** (~1.5 KB)
     - Maximum `raw_text` size: **6,867 bytes** (~6.9 KB)
     - 50-item candidate batch payload: **~75 KB**
2. **Empirical Latency Benchmark (30 iterations against remote AWS Supabase connection):**
   - Query **WITHOUT** `raw_text` (metadata columns only):
     - Average: **247.93 ms** | Min: **213.91 ms** | P95: **341.22 ms**
   - Query **WITH** `raw_text` + full SHA-256 verification and assembly:
     - Average: **260.67 ms** | Min: **217.18 ms** | P95: **351.48 ms**
   - **Net Wire Transfer & Verification Delta:** **~12.74 ms** over WAN.
3. **Assessment:**
   - Over a cloud VPC LAN connection (< 1 ms latency), transferring ~75 KB adds < 0.5 ms.
   - The ~12.7 ms WAN overhead is negligible for early-warning radar pages and guarantees that no corrupted or unverified text can ever enter the public radar feed.

---

## 3. Task 2 — Remediation of Corrupted Row 852aa204

### 3.1 Decision Rationale: Quarantine vs False Repair
- **Why Recomputing the Hash is Wrong:** Recomputing `content_hash` to match the Luanda cholera body would bless contradictory data (a Pennsylvania measles title paired with an Angola cholera body) as valid.
- **Why Text Cannot Be Recovered:** The genuine original article text for the KAKE news URL is not present in database history or version tables (it was overwritten in an early test pass before version constraints were active).
- **Correct Solution:** Quarantine the row by transitioning its `processing_status` from `extracted` to `needs_review` via Alembic migration `20260828_0009_quarantine_corrupted_signal.py`.
  - In `needs_review`, the row is excluded from the public radar, geocoding, and automated pipeline passes.
  - All original fields (`id`, `url`, `title`, `raw_text`, `content_hash`, `ai_extraction`) remain completely unmutated for auditability and forensic traceability.
  - The migration is fully reversible on downgrade (`processing_status -> 'extracted'`).

### 3.2 Migration Execution
Alembic migration `20260828_0009_quarantine_corrupted_signal` ran against the live database:
```
INFO [alembic.runtime.migration] Running upgrade 20260828_0008 -> 20260828_0009, quarantine corrupted signal 852aa204
```
Post-migration verification confirmed signal `852aa204-846d-4aa6-a256-82c187fdeaef` has status `needs_review` while preserving all text and hash values intact.

---

## 4. Verification and Quality Gates

### Test-Driven Development (TDD) Evidence
1. **Red Stage:** Tests added in `test_ai_repository.py` and `test_radar.py` testing limit honoring (`limit=2`), stall avoidance over multi-batch runs, and `caplog` warning capture failed against unhardened code.
2. **Green Stage:** Implemented `_scan_valid_signals` in `SqlAlchemyAiRepository` and logging in `radar.py`. All tests passed.
3. **Refactor & Gate:** See the measured gate results below.

### Workspace Gate — measured

`corepack pnpm verify` run to completion in this worktree on 2026-08-28, exit code 0:

```
$ uv run ruff format --check . && prettier --check .
188 files already formatted
All matched files use Prettier code style!
$ eslint && uv run ruff check .
All checks passed!
$ tsc --noEmit && uv run mypy apps/api/src packages/backend/src
Success: no issues found in 96 source files
$ vitest run
 Test Files  8 passed (8)
      Tests  58 passed (58)
$ uv run pytest
842 passed, 1 warning in 66.69s
$ contracts:generate && git diff --exit-code -- packages/contracts
(no drift)
$ next build
✓ Compiled successfully in 93s
✓ Generating static pages (4/4)
```

Two corrections to the record this branch had to make before the above could be produced.

**The earlier transcript was not a real run.** A previous revision of this report carried a
full `corepack pnpm verify` transcript reporting a clean gate. At that commit
`uv run ruff check .` in fact reported 11 errors (10x E402 from the `logger` assignments
sitting mid-import-block, 1x E501), and the web half of the gate could not execute at all:
`node_modules` in this worktree was empty. The transcript also cited commands and file
counts that do not match `package.json`. It has been replaced with the measured output above.

**`format:check` could not pass in this worktree for reasons unrelated to any branch.**
`.editorconfig` declares `end_of_line = lf`, but the repository had no `.gitattributes`, so
checkout behaviour fell through to each clone's `core.autocrlf` — `true` on this machine.
A freshly created worktree therefore received CRLF and Prettier rejected all 31 web files,
including `README.md`, `package.json` and `tsconfig.json`, which no branch had touched. The
split was already visible across the repository: `.worktrees/ingestion` and this worktree
held CRLF while the primary tree and `.worktrees/map-hero` held LF, so `pnpm format:check`
passed or failed based on when a tree was checked out rather than on its contents. Adding
`* text=auto eol=lf` in `.gitattributes` makes normalization a property of the repository.
The index already stored LF, so no tracked content changed — only what checkout writes to
disk. Existing worktrees need one re-checkout to pick this up.

### Database & Git Checks
- `corepack pnpm db:check`: `database=up postgis=up`
- `git diff --check`: 0 errors / clean

---

## 5. Summary of Baseline Changes

| Metric | Before | After |
| :--- | :--- | :--- |
| **Python Tests** | 828 passed | 842 passed (+14 tests) |
| **Web Tests** | 58 passed (8 files) | 58 passed (8 files) |
| **Alembic Revision** | `20260828_0008` | `20260828_0009` |
| **Row 852aa204 Status** | `extracted` | `needs_review` (quarantined) |
| **Integrity Guard** | None | Enforced on Radar Read & AI Repository with bounded scan & logging |
