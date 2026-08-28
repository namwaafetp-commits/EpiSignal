# Handoff — Sub-Project C2: The English Brief

**Date:** 2026-08-28
**Branch:** `main` (clean, 756 passing Python tests, 10 web tests)
**Head:** `L` complete and verified. The whole pipeline runs from one command, records each run in `pipeline_runs`, and is scheduled daily.
**State:** `P0`–`P3`, `A`, `B`, `C`, `D1`, `D2a`, and `L` are complete, verified, and merged. `C2` is **designed and planned**. **Your task is to implement Sub-Project C2, task by task, from the committed plan.**

---

## Why this item, and why now

An extraction currently carries one free-form `summary`: up to 400 characters,
written in whatever language the article was written in. Nothing can lay two of
them out the same way, and a reader who does not read Portuguese learns nothing
from a Portuguese outbreak report the system has already paid a model to read.

The operator asked for briefs that read in English as five bullets in an
epidemiologist's order. That is a change to what extraction *writes*, so it is
its own item rather than something the radar (`E`) does at render time.

It goes before `E` because an extraction is paid for once. Fixing the shape now
means the corpus grows in its final form; fixing it after `E` means paying a
second time for every article already read.

---

## What Sub-Project C2 builds

1. **An English title.** `title_english`, stored beside the publisher's
   headline and never over it.
2. **A brief.** Exactly five bullets, one per slot, in a fixed order:
   `what_where`, `counts`, `timing`, `spread`, `reporting`.
3. **A stated absence.** A slot the article never addresses is stored with
   `reported: false` and text that says what is missing.
4. **A version.** `ai_extraction` carries `extraction_schema_version`, stamped
   by the repository, and a tolerant model that can still read rows written
   before any of this existed.
5. **A backfill.** `pnpm extract:backfill` re-extracts rows below the current
   version, bounded by the same cost guards, and returns each to `extracted` so
   geocoding and matching run again.

---

## Scope note: this changes one stage's output

`C2` touches `ai/` and the one line in `events/repository.py` that reads what
`ai/` wrote. It adds no table, no migration, and no column.

If you find yourself changing what discovery finds, what dedupe rejects, what
geocoding resolves, how clustering matches, or what the scheduler calls, you
have left this item. Stop and report. The single deliberate exception is
`events/repository.py`, which task 7 changes because task 6 would otherwise
silently break the way matching reads a stored extraction.

---

## Start here

Read in this exact order:

1. This file (`HANDOFF.md`);
2. `STATUS.md` — the current position, the 13-task ledger, and the verified baseline;
3. `ROADMAP.md` — where `C2` sits, between `C` and `D1`;
4. `docs/agents/workflow.md` — the planner and worker contract and the completion gate;
5. `docs/superpowers/specs/2026-08-28-english-brief-design.md` — the design you are implementing;
6. `docs/superpowers/plans/2026-08-28-english-brief.md` — the 13 tasks, in order;
7. `AGENTS.md` — model routing, project skills, TDD rules, provenance principles;
8. `CONTEXT.md` — the naming authority. Task 12 adds *brief*, *slot*, and *English title* to it; read the existing **Judgement** section first so the additions match its voice;
9. `docs/reports/2026-08-28-subproject-l-report.md` — the outgoing item's completion report;
10. `docs/handoffs/2026-08-28-l.md` — the briefing `L` was built under.

When `C2` reaches `verified`, archive this file to `docs/handoffs/2026-08-28-c2.md`
before rewriting it for the next item. Do not overwrite it in place.

---

## Windows environment facts

- **Python:** Run all commands through `uv run`. Do not activate virtual environments manually. Bare `python` is not on `PATH`; use `uv run python`.
- **Node / pnpm:** `pnpm` is not on `PATH`, but `corepack` ships with Node and is. Always enter the workspace through `corepack pnpm <command>`.
- **PowerShell:** Commands run under Windows PowerShell 5.1 (no `&&`, no ternary, no `??`). Chain with `;`.
- **UTF-8 BOM:** Strip UTF-8 BOM from generated scripts or use standard python writers.
- **This is a shared working tree.** Other agents commit to `main` in this same directory. Commit only the files your task names; never `git add -A`.

---

## Verified baseline

```powershell
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy apps/api/src packages/backend/src
corepack pnpm verify
```

**Expected baseline output at `5e148ce`**, every line of it observed by the
worker rather than copied from a report:

- `783 passed, 1 warning`
- `All checks passed!`
- `181 files already formatted`
- `Success: no issues found in 93 source files`
- Web: `10 passed (10)`, 3 test files
- `corepack pnpm verify` exits 0.

If your first run disagrees with any of these before you have changed anything,
stop and report it. Something moved that this briefing does not know about.

The database is at migration revision `20260828_0008_pipeline_runs`. This item
adds no migration, so it should still be there when you finish.

---

## Testing rules that are not optional

- **No test touches a database, a socket, or a model.** There is no `conftest.py`
  and no fixture database. Repository tests use a hand-written `FakeSession` —
  the one at the top of `packages/backend/tests/test_ai_repository.py` is the
  one this item extends. Model calls use `ScriptedModel` from
  `packages/backend/tests/test_ai_classify.py`.
- **Only task 13 touches the live database or spends money.** Tasks 1 through 12
  need no key, no network, and no database.
- **Test-first, red then green.** The plan gives you the failing test, the command
  to prove it fails, and the expected failure for every task.
- **Task 2 must be one commit.** Removing `summary` from the contract breaks every
  payload in the suite; the schema change and the fixture updates land together
  or the history has a commit nobody can bisect through.

---

## Invariants for Sub-Project C2

1. **The brief never fills a slot the article left empty.** `reported: false` and
   a line saying what is missing. A model told to always produce five bullets
   from an article supporting three will invent two, and every review of this
   item checks that first.
2. **Spans stay in the article's language.** `check_grounding` requires each
   `source_span` to occur verbatim in the body. If you find yourself translating
   a span to make grounding pass, you have inverted the design.
3. **The version is written by code, never by the model.** A version a model can
   choose is a version that lies the moment the model is confused.
4. **Strict on the way in, tolerant on the way back.** `Extraction` keeps
   rejecting a missing brief. `StoredExtractionPayload` reads rows this system
   already wrote, including rows that predate the brief.
5. **A rejected re-extraction changes nothing.** The row already holds an answer
   that passed these same checks. The backfill does not demote it to
   `needs_review`, and it does not overwrite it.
6. **`needs_review` rows are never backfilled.** A human owes them a decision,
   and `M` is the item that collects it.
7. **Counts only on stdout.** No key, no prompt, no article body, in any runner's
   output or in any error message. `type(error).__name__` and nothing else.

---

## Settled decisions — do not reopen

- Five slots, always, in the order the enum declares them. A brief with four
  points, six points, a duplicated slot, or slots out of order is rejected, not
  sorted.
- One model call, not two. The model that reads the article writes the English
  title and the bullets in the same response as the counts. Translation never
  triggers escalation — `CONTEXT.md` already forbids escalating on language.
- The free-form `summary` field leaves the contract. The `signals.summary`
  *column* stays, holding the five bullet texts joined by newlines.
- No migration. `ai_extraction` is already JSONB.
- The backfill is not wired into the daily chain. A future prompt change must not
  be able to silently re-extract a corpus of thousands.

---

## Known trap: the tolerant reader and mypy

`StoredExtractionPayload` widens two of its parent's fields, which mypy `strict`
rejects without a narrow `# type: ignore[assignment]` on the `title_english`
line. That ignore is required and used — `warn_unused_ignores` will tell you if
it ever stops being needed. Do not widen it to a bare `# type: ignore`, and do
not solve it by making the strict model lenient: the strict model is the only
thing forcing a model to return a brief at all.

---

## Carried forward from `L`

- The daily chain runs `ingest_who → ingest_ecdc → discover → dedupe → extract →
  geocode → match` under an advisory lock, and records each run in
  `pipeline_runs`.
- `EPISIGNAL_OPENROUTER_API_KEY` was missing for the whole of `L`, which is why
  its live run recorded `extract failed (RuntimeError)`. The operator set it on
  2026-08-28. Task 13 is the first run that will exercise it — if extraction
  fails for a *different* reason, that is a finding worth reporting, not
  something to work around.
- The last recorded backlog was `normalized=46`, `needs_review=7`,
  `duplicate=1`. Those 46 will be classified and extracted into the new shape by
  a normal run; the handful already extracted are what the backfill is for.

---

## The completion gate

`C2` becomes `verified` only when every one of these is true:

1. Every task in the plan is ticked in `STATUS.md`.
2. `corepack pnpm verify` ran in your session and reported zero failures.
3. The real output of that run — the test counts, not a claim — is quoted in
   `docs/reports/2026-08-28-subproject-c2-report.md`.
4. The report is committed.
5. `STATUS.md`'s verified baseline is updated to the commit you ran at.

You do not set `C2` to `verified` in `ROADMAP.md`. Hand back to the planner and
report what ran, what it printed, and anything in the spec you found to be wrong.
