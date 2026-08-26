# Handoff — WHO Disease Outbreak News ingestion

**Date:** 2026-08-26
**Branch:** `feat/who-don-ingestion`
**Worktree:** `D:\Projects\Side Project\EpiSignal\.worktrees\ingestion`
**State:** Tasks 1–10 complete. Live Supabase verification passed. Worktree clean, 123 tests passing.

This slice ingests WHO Disease Outbreak News documents into the `signals` table.
All plan steps are complete and ticked. The branch is ready for its finishing
workflow; read the plan and approved design before integrating it.

## Start here

```powershell
cd "D:\Projects\Side Project\EpiSignal\.worktrees\ingestion"
uv sync
uv run pytest -q          # expect 123 passed
```

Windows machine. Python tooling is `uv` — prefix every Python command with `uv run`. `pnpm` is NOT on PATH; use `corepack pnpm`. PowerShell 7 (`pwsh`) is not installed either; scripts run under Windows PowerShell 5.1.

## What this project is

EpiSignal turns public health reporting into traceable events. Its core principle: **never show a number without the evidence behind it.** That principle is not decoration — it decided several design points below, and it should decide yours.

The foundation slice (already merged to `main`) built the schema, a FastAPI service, a Next.js shell, and canonical seeds. This slice put the first real, traceable WHO documents in the configured Supabase database without fabricating outbreak data.

## What is done

| Task | Commit | What it gives you |
| --- | --- | --- |
| 1 | `599d1c2`, `b71c0f7` | Migration `20260826_0002`: signal identity is now `(url, content_hash)`, and `content_hash` is `NOT NULL` |
| 2 | `e476efa`, `eba35b0` | `ingestion/urls.py` — `canonicalize_url`, pure |
| 3 | `3e48e99`, `af68354` | `ingestion/fingerprint.py` — `content_hash`, SHA-256 hex, NFC-normalised |
| 4 | `5fe1426`, `7bc969b` | `ingestion/documents.py` and `ingestion/protocol.py` — the contracts and both Protocols |
| 5 | `ac61f40`, `09c008a` | `ingestion/who_don.py` — `WhoDonConnector.normalize` plus `strip_html` and `parse_utc` |
| 6 | `a743721`, `901ab5a` | Credential-free WHO HTTP fetching, strict response validation, paging, retry, and inclusive backfill semantics |
| 7 | `21a8add` | Thin SQLAlchemy `SignalRepository` adapter |
| 8 | `5934207` | Protocol-only ingestion pipeline with per-document isolation and in-memory tests |
| 9 | `d43e9d4` | CLI, `ingest:who`, corrected WHO seed URL, and per-source signal counts |
| 10 | — | Live migration, seed, first ingestion, idempotency proof, evidence audit, and full backend/frontend verification |
| — | `3fc5df0` | Corrections to the plan text itself (see "Plan corrections" below) |

The live database has migration `20260826_0002`, 29 diseases, two sources, and
12 WHO signals. A first run inserted 12; immediate reruns inserted 0 and skipped
12. All later-slice extraction fields remain null.

## What remains

Choose the finishing workflow: merge locally into local `main`, open a PR, or
keep the branch/worktree. Do not use `origin/main` as the base.

## Architecture, and why it is shaped this way

```text
packages/backend/src/episignal_backend/ingestion/
  urls.py          canonicalize_url            pure
  fingerprint.py   content_hash                pure
  documents.py     RawDocument, NormalizedSignal
  protocol.py      SourceConnector, SignalRepository
  who_don.py       WhoDonConnector             the only module that will open a socket
  repository.py    SQLAlchemy storage adapter
  pipeline.py      ingestion decisions
```

`pipeline.py` must import the two Protocols and **nothing else** — no SQLAlchemy, no httpx. That is what keeps every ingestion decision testable with in-memory fakes. Every test in this repository runs without credentials and without network access. Keep it that way.

`NormalizedSignal` is deliberately a **subset** of the `signals` columns. `summary`, `relevance_score`, `public_health_relevant`, `ai_extraction`, `ai_model` and `ai_processed_at` are absent, and `extra="forbid"` makes that structural. They belong to a later extraction slice. Writing a placeholder into an evidence column would be a fabricated value.

## Things that will bite you

These were found during implementation and review.

1. **`hash(RawDocument(...))` raises `TypeError`** despite `frozen=True`, because `payload` is a dict. The model *looks* set-safe and is not. Do not put documents in a set in Task 8.

2. **`isinstance` against a `runtime_checkable` Protocol checks member names only, not signatures.** A class with `fetch(self)` — wrong arity — passes `isinstance(..., SourceConnector)`. mypy's structural checking is the real guard. Task 7's test has been rewritten to include a typed `_conforms` helper for exactly this reason; keep it.

3. **`content_hash` must match `^[0-9a-f]{64}$`.** Synthetic digests in test fixtures must be valid lowercase hex. This already broke the plan's Task 8 fixture once (see below).

4. **`language` is capped at 2–8 characters** to match `String(8)` on the column. A full BCP-47 tag will be rejected at the boundary rather than at `INSERT`.

5. **The metadata naming convention derives unique-constraint names from table + first column.** Any new `UniqueConstraint` needs an explicit `name=`, or it will collide.

6. **`ruff format` reformats fenced code inside Markdown.** `extend-exclude = ["*.md"]` is set in the root `pyproject.toml` to stop it rewriting the specs. Do not remove it.

7. **`ruff format --check .` is part of the gate.** When it flags a file, run `uv run ruff format packages database apps/api` and re-run the checks.

## Plan corrections already applied (commit `3fc5df0`)

The plan text was wrong in two places. Both are fixed in the file; this note is so you do not think the file drifted.

- **Task 8's fake** built `content_hash=content[0] * 64`. For the `"unparseable"` sentinel that is `"u" * 64`, which is not hex and is rejected at construction by the Task 4 pattern. The test would have failed before `run_ingestion` was called and looked like a pipeline bug. It now derives real digests via `fingerprint.content_hash`.
- **Task 7's conformance test** relied on `isinstance` alone. It now also calls a typed `_conforms` helper so mypy performs the real structural check.

## Verified facts about the WHO API

Checked live on 2026-08-26 — do not re-derive these from the seed data, which was wrong.

- The endpoint is `https://www.who.int/api/news/diseaseoutbreaknews`. **The RSS URL in `database/seeds/sources.json` is dead (HTTP 404)** and Task 9 replaces it.
- `$orderby=PublicationDateAndTime desc` and `$top=N` are honoured.
- Each item carries `Id`, `DonId`, `UrlName`, `ItemDefaultUrl`, `PublicationDate`, `PublicationDateAndTime`, `LastModified`, `Title`, and the body split across `Overview`, `Epidemiology`, `Assessment`, `Advice`, `Response`.
- `DonId`, `UrlName` and `ItemDefaultUrl` agree: `2026-DON615` and `/2026-DON615`.
- The public URL is `https://www.who.int/emergencies/disease-outbreak-news/item/{UrlName}` and resolves.

## Review findings worth carrying forward

Two-stage review — spec compliance, then code quality — caught real defects on four of five tasks. The pattern that worked: tell the reviewer to verify by **running** the code, not by reading the diff, and to report actual output. Several findings only surfaced that way.

Genuine defects caught, as calibration for how carefully this code needs reading:

- **`<td>45</td><td>12</td>` produced `"4512"`** — a number the source never printed, in a column the project treats as evidence. A later extraction slice would have reported 4,512 cases where the document said 45.
- **`content_hash` accepted `"A"*64`.** An uppercase digest would not error; it would silently insert a duplicate version of a document already stored — the exact failure this slice exists to prevent.
- **`"Côte d'Ivoire"` hashed differently** depending on whether the accent was precomposed or a combining character, so a CMS re-save would have produced a spurious new version on every run.
- **`strip_html` decoded entities twice**, so `&amp;lt;p&amp;gt;` became a literal `<p>` inside the evidence text.
- **`signals.content_hash` was nullable**, and PostgreSQL treats NULLs as distinct in a unique constraint — so the identity key would not have constrained anything for null hashes.

## Workflow

Executed with test-first implementation, per-task gates, lean task reviews, a
final two-axis review, and live verification. Final review found and corrected
publication-watermark evidence loss: normal runs now recheck a rolling 90-day
publication-or-modification window, so recent revisions and failed documents
are retried without cursor gaps.

## Finishing

When all ten tasks are done, use `superpowers:finishing-a-development-branch`. The foundation slice merged with `--no-ff` from a worktree at `.worktrees/foundation`, then the worktree was removed and the branch deleted; the same shape applies here.

Note that local `main` is currently **ahead of `origin/main` by 17 commits** — the foundation slice was merged locally but never pushed. Do not branch from `origin/main`.

## Repository conventions

- Ruff line length 100, `select = ["E", "F", "I", "UP", "B", "SIM"]`
- mypy strict
- Pydantic 2 — `ConfigDict`, `field_validator`
- Comments explain *why*, not *what*. Code, docs, commits and issues are professional prose
- `AGENTS.md` at the repo root carries the project's own agent instructions, including a chat style preference and model-routing tiers. Read it.
