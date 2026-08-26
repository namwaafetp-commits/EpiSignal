# Handoff — WHO ingestion and evidence browser

**Date:** 2026-08-26
**Branch:** `feat/who-don-ingestion`
**Worktree:** `D:\Projects\Side Project\EpiSignal\.worktrees\ingestion`
**State:** Tasks 1–10 are committed and live-verified. The evidence-browser
slice is committed, followed by one small uncommitted review correction that
still needs the full gate and a commit.

## Start here

Run every command from this worktree. Do not switch to `main` and do not use
`origin/main` as a base; local `main` contains 17 commits not present there.

Read, in order:

1. this file;
2. `AGENTS.md`;
3. `docs/superpowers/specs/2026-08-26-signal-evidence-browser-design.md`;
4. for ingestion details,
   `docs/superpowers/plans/2026-08-26-who-don-ingestion.md` and
   `docs/superpowers/specs/2026-08-26-who-don-ingestion-design.md`.

Windows environment:

- Python commands use `uv run`.
- `pnpm` is not on `PATH`; use `corepack pnpm`.
- PowerShell 7 is absent. Commands run under Windows PowerShell 5.1.

## Current git state

Latest commits:

```text
08a3e09 fix: validate displayed outbreak evidence
fda99f5 feat: show stored outbreak evidence on the web
99a1c0d fix: preserve ingestion evidence across reruns
d43e9d4 feat: add the ingest command and correct the WHO source URL
5934207 feat: run the source ingestion pipeline
```

The following uncommitted correction was developed RED→GREEN after the final
spec recheck found that whitespace-only `raw_text` could make the whole web feed
unavailable:

```text
M apps/web/src/lib/api-signals.ts
M packages/backend/src/episignal_backend/evidence.py
M packages/backend/src/episignal_backend/ingestion/documents.py
M packages/backend/tests/test_evidence.py
M packages/backend/tests/test_ingestion_documents.py
```

The correction does three aligned things:

- `NormalizedSignal` rejects blank evidence while returning valid source text
  unchanged;
- the evidence query excludes legacy NULL, empty, and whitespace-only rows from
  its items, total, and source count;
- the web runtime validator applies the same non-blank rule.

Observed RED:

```text
test_evidence.py: expected total 3, received 4
test_ingestion_documents.py: ValidationError DID NOT RAISE
```

Observed GREEN after the implementation:

```text
uv run pytest -q packages/backend/tests/test_evidence.py
1 passed

uv run pytest -q packages/backend/tests/test_ingestion_documents.py -k blank_evidence
1 passed

corepack pnpm --filter @episignal/web exec vitest run src/lib/api-signals.test.ts
3 passed
```

## Exact next steps

1. Inspect the uncommitted diff only; do not redo the completed broad review.
2. Run the full gates from this worktree:

   ```powershell
   uv run pytest -q
   uv run ruff check .
   uv run ruff format --check .
   uv run mypy packages/backend/src apps/api/src
   corepack pnpm test:web
   corepack pnpm lint:web
   corepack pnpm typecheck:web
   corepack pnpm build
   ```

   The Python suite should now report 126 tests. That count is an expectation,
   not a completed verification: the prior full run was interrupted after the
   new blank-evidence test was added.

3. If all gates pass, commit the five product/test files with:

   ```powershell
   git add apps/web/src/lib/api-signals.ts `
     packages/backend/src/episignal_backend/evidence.py `
     packages/backend/src/episignal_backend/ingestion/documents.py `
     packages/backend/tests/test_evidence.py `
     packages/backend/tests/test_ingestion_documents.py
   git commit -m "fix: reject blank source evidence"
   ```

   Commit `HANDOFF.md` with the handoff/documentation change as appropriate.

4. Restart the web/API only after all edits and commits are finished:

   ```powershell
   corepack pnpm dev
   ```

   Verify `http://127.0.0.1:8000/api/v1/signals` reports `total=12`,
   `source_count=1`, twelve returned items, and non-blank `raw_text` for every
   item. Then load `http://localhost:3000/` and confirm the page shows the 12
   report cards, collection dates, expandable evidence, publisher links, and
   the limited-coverage warning.

5. Run one focused spec recheck for the whitespace finding. The broad standards
   recheck already approved with no Critical or Important findings.

6. Use the branch-finishing workflow. Offer merge to local `main`, PR, or keep
   the worktree. Do not merge or push without the user's choice.

## What is complete

WHO ingestion Tasks 1–10 are implemented. Important commits:

| Work | Commits |
| --- | --- |
| Versioned signal identity | `599d1c2`, `b71c0f7` |
| URL canonicalization and hashing | `e476efa`, `eba35b0`, `3e48e99`, `af68354` |
| Ingestion contracts and WHO normalization | `5fe1426`, `7bc969b`, `ac61f40`, `09c008a` |
| WHO HTTP paging/retries | `a743721`, `901ab5a` |
| Repository and Protocol-only pipeline | `21a8add`, `5934207` |
| CLI, source seed correction, schema counts | `d43e9d4` |
| Revision-safe rolling activity window | `99a1c0d` |
| Read-only evidence endpoint and homepage | `fda99f5` |
| Evidence runtime validation and query proof | `08a3e09` |

The evidence browser adds:

- `GET /api/v1/signals`, bounded to `limit=1..50` and `offset>=0`;
- newest-first exact evidence with publisher, publication, and collection time;
- live evidence/source counts;
- generated OpenAPI TypeScript contracts;
- runtime validation of successful HTTP responses before anything is displayed;
- an honest loading, unavailable, empty, and limited-coverage UI.

It does not add search, maps, event matching, extracted case counts, summaries,
relevance scores, or AI fields.

## Verification already completed

Before the final uncommitted whitespace correction:

```text
uv run pytest -q
125 passed; one existing Starlette TestClient deprecation warning

uv run ruff check .
All checks passed!

uv run ruff format --check .
57 files already formatted

uv run mypy packages/backend/src apps/api/src
Success: no issues found in 36 source files

corepack pnpm test:web
3 files passed; 10 tests passed

corepack pnpm lint:web
exit 0

corepack pnpm typecheck:web
exit 0

corepack pnpm build
exit 0; `/` is server-rendered dynamically
```

The production build warns that the repo expects Node 22.19 while this machine
has Node 24.19. The tests also emit existing Vite future warnings. These are not
failures introduced by the slice.

`corepack pnpm verify` is not a clean aggregate baseline: its project-wide
Prettier step flags 14 untouched files under `apps/web`. Do not bulk-format
unrelated files to hide that baseline issue. The modified web files passed a
focused Prettier check.

## Live Supabase proof

The configured project contains:

```text
migration 20260826_0002 applied
diseases=29
sources=2
WHO signals=12
```

First ingestion inserted 12. Repeated activity-window runs reported:

```text
inserted=0 skipped=12 failed=0
```

The count remained 12 and all later-slice fields (`summary`, relevance,
public-health classification, and all AI fields) remained NULL. The read-only
endpoint later returned 12 items from one source and every item had stored text.

## Evidence invariants

EpiSignal's governing rule is: never show a number without the evidence behind
it. Preserve these consequences:

- `signals.raw_text` is evidence. Keep it exact; do not trim, summarize, decode
  twice, or place a placeholder in it.
- A WHO revision appends a new `(url, content_hash)` row. It never overwrites
  prior evidence.
- Normal runs recheck a rolling 90-day publication-or-modification window.
  Stored publication dates are not a cursor.
- `pipeline.py` imports the two Protocols from `ingestion/protocol.py` and no
  SQLAlchemy or `httpx` code.
- Automated tests use no credentials and no network.
- `NormalizedSignal` remains a subset of `signals`; later extraction and AI
  fields do not belong in it.

## Multi-source expansion

Twelve WHO reports from one source are an ingestion proof, not usable global
surveillance. The homepage says this explicitly. The approved evidence-browser
design specifies the next source order:

1. ECDC communicable-disease threat reports;
2. Africa CDC outbreak updates;
3. PAHO epidemiological alerts and updates;
4. US CDC Health Alert Network and outbreak notices;
5. selected national public-health agencies chosen by geographic gaps;
6. ReliefWeb or ProMED only after licensing and provenance review.

Each needs a source-specific design that verifies its official interface,
terms, paging, revision semantics, languages, evidence boundaries, and overlap.
Do not build a generic scraper or treat raw source count as coverage quality.

## Traps worth retaining

1. `RawDocument` is frozen but contains a dict, so it is not hashable.
2. `runtime_checkable` Protocol `isinstance` checks names, not signatures; mypy
   structural checks are the real conformance gate.
3. Test content hashes must match lowercase `^[0-9a-f]{64}$`.
4. Explicit names are required for new unique constraints under the metadata
   naming convention.
5. The old WHO RSS seed URL returns 404. The working endpoint is
   `https://www.who.int/api/news/diseaseoutbreaknews`.
6. On Windows, Uvicorn's reloader watches the whole worktree. Editing tests while
   `corepack pnpm dev` runs prompts `Terminate batch job (Y/N)?` and kills both
   the API and web process under `concurrently`. Start it after edits are done.
7. The in-app browser successfully displayed all 12 cards and expanded exact WHO
   text before the last correction. A later automated reload was blocked by the
   browser URL policy. The current dev server is stopped; restart it manually.
