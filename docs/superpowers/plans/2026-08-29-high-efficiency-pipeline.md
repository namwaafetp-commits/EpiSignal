# High-Efficiency Pipeline and Gemini Transition — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Also load the project-local `lean-build`, `tdd`, and `migration` skills before Task 1. Before completion, load `code-review` and then `verify-and-stop`. Tick each task in `STATUS.md` in the same commit as the work.

**Item:** `O`

**Goal:** Cut measured monthly AI spend below one US dollar — confirmed from the `ai_requests` ledger, never estimated — through four levers in order: English-only discovery, a Gemini 2.5 Flash-Lite roster transition with the OpenRouter ladder as fallback, an event delta pass, batch scheduling, and a measurement-gated pre-group stage that ships default-off.

**Architecture:** The GDELT client enforces the query-rule language in both the request operator and the result guard. The model roster gains a provider column; the runner builds one adapter per configured provider and the ladder resolves each rung to its provider's adapter, so fallback stays tier-climbing. A `GeminiChatModel` implements the existing one-method `ChatModel` boundary with structured output and zero temperature. After a cluster attaches to an event observed inside the follow-up window, a delta pass compares the two latest briefs and writes what changed onto the new observation row. Scheduled extraction gains a Gemini batch submit/poll cycle with real-time fallback. A pre-group stage groups normalized signals by rule group, publisher country, and day window; one representative is extracted, the rest defer until resolution or expiry, and nothing deferred is ever counted as evidence. The stage sits behind a default-off flag whose final position is decided by measured trailing spend.

**Tech stack:** Python 3.12, SQLAlchemy 2, Pydantic v2, httpx, pytest, Alembic-style reversible revisions under `database/`, the existing GDELT DOC 2.0 and Gemini/OpenRouter HTTP APIs.

**Design:** [docs/superpowers/specs/2026-08-29-high-efficiency-pipeline-design.md](../specs/2026-08-29-high-efficiency-pipeline-design.md)

**Incoming verified baseline:** `2499e4e` on `main` — 848 Python tests and 58 web tests passed, Ruff/ESLint/mypy/tsc clean, clean contract diff, Next production build green. Planner documentation through `89aaeda` is clean. Verify with `git status` before Task 1 and stop if the tree is dirty.

---

## Scope check

The levers are independent slices that share one completion gate: a measured
sub-dollar month. Language (Tasks 1–2) and the provider transition (Tasks 3–6)
each land as working, testable software on their own. The delta pass (Tasks
7–8) and batch mode (Tasks 9–10) stack on the transition without depending on
each other. The pre-group stage (Tasks 11–13) is the only lever that changes
selection semantics, which is why it ships last, behind a flag, decided by the
measurement gate in Task 13.

## Rules and stop conditions

- Work in the numbered order. Do not start the pre-group tasks before Task 13's
  measurement exists, and do not enable the pre-group flag anywhere by default.
- Every behavior change is red → green → refactor. Run the named failing test
  before implementation and record the expected failure in the commit notes
  when it is surprising.
- At Task 1, set `O` from `planned` to `building` in `ROADMAP.md`. Thereafter
  the worker changes only task ticks and the verified baseline in `STATUS.md`;
  it does not redesign the roadmap, spec, or plan.
- Every schema change is a reversible revision with a tested downgrade. The
  query-rule seed change deactivates `any` rows; it never deletes them, and the
  downgrade reactivates them.
- Tests through Task 13 open no socket and use no live database and no live
  provider. Tasks 6 and 14 are the only live tasks.
- Failure posture everywhere: counts and exception types in logs, never
  prompts, keys, article text, or exception messages.
- `ModelUnavailable` remains the only unavailable signal: a signal stays
  selectable, never goes to review, and the ladder shortens when a provider
  key is missing rather than the run failing.
- Deferred signals are never attached to events and never count toward the
  evidence score. If a task finds itself needing either to make a test pass,
  stop and return to the planner.
- If the Gemini API's current surface cannot honor the structured-output
  contract the passes build, or batch pricing differs from the design's
  assumption, stop and record the fact for the planner instead of adapting the
  schema silently.
- Task 6 requires `EPISIGNAL_GEMINI_API_KEY`. If it is absent, record the
  blocker in `STATUS.md` exactly as the OpenRouter key once was, and continue
  with Tasks 7–13, which need no live provider.

## Target file structure

**Create:**

- `packages/backend/src/episignal_backend/ai/gemini.py`
- `packages/backend/src/episignal_backend/ai/spend.py`
- `packages/backend/src/episignal_backend/events/delta.py`
- `packages/backend/src/episignal_backend/ingestion/pregroup.py`
- matching test files beside each
- two reversible revisions under `database/` (provider and purpose vocabulary;
  pre-group tables) plus the query-rule deactivation data revision
- `docs/reports/<run-date>-subproject-o-report.md`

**Modify:**

- `packages/backend/src/episignal_backend/ingestion/gdelt/api.py`
- `database/seeds/gdelt_queries.json`, `database/seeds/ai_models.json`
- `packages/backend/src/episignal_backend/db/types.py`
- `packages/backend/src/episignal_backend/models/ai.py`
- `packages/backend/src/episignal_backend/ai/documents.py`
- `packages/backend/src/episignal_backend/ai/ladder.py`
- `packages/backend/src/episignal_backend/extract_runner.py`
- `packages/backend/src/episignal_backend/events/event_runner.py` and
  `events/documents.py`
- `packages/backend/src/episignal_backend/schedule/stages.py` and
  `pipeline_runner.py`
- `packages/backend/src/episignal_backend/config.py`

## Tasks

1. **Enforce the query-rule language in the GDELT client.** Test-first: a rule
   with `language="en"` sends the `sourcelang:eng` operator and a result
   reporting a non-English language is dropped and counted; a rule with
   `language="any"` sends no operator and drops nothing. Red test against
   `GdeltDocClient.search` with a fake transport, then implement. No schema
   change. Set `O` to `building` in this commit.

2. **Pin the seed library to English.** Add every rule's `"language": "en"` to
   `database/seeds/gdelt_queries.json`; because the natural key is
   `(query, language)`, add a reversible data revision that deactivates the
   `any` rows whose queries now carry `en`. Seed test asserts exactly one
   active row per query after reseeding; downgrade test asserts `any` rows are
   active again.

3. **Make provider a roster fact.** Reversible revision adding the provider
   vocabulary (`openrouter`, `gemini`) and the `ai_models.provider` column
   defaulting to `openrouter`; extend `ModelSpec` accordingly. Seed
   `google/gemini-2.5-flash-lite` as the active tier-1 row at Gemini list
   prices and demote the current tier-1 row to inactive in the same seed
   revision. Roster and repository tests green.

4. **Build `GeminiChatModel`.** Contract tests with a fake transport:
   structured output requested through the same response-schema fields
   `ChatRequest` already carries, temperature honored, `ModelUnavailable`
   raised on refusal, timeout, and quota, latency recorded, and no key or
   prompt ever reaching an exception string. Implement against the
   `ChatModel` protocol — one `complete` method, nothing else.

5. **Resolve rungs through provider adapters.** The runner builds an adapter
   map from configured keys (`EPISIGNAL_OPENROUTER_API_KEY`,
   `EPISIGNAL_GEMINI_API_KEY`); a provider whose key is missing contributes no
   adapter and its rungs are skipped with the `NoModelsConfigured` semantics
   preserved. Ladder tests cover the mixed ladder, the missing-key skip, and
   that tier climbing still crosses providers. Fake-driven only.

6. **Validate Gemini live on ten to twenty real signals.** With the key set,
   run the extract stage over the selected range real-time; record per-signal
   acceptance, slot adherence, grounding pass rate, and the cost rows written.
   A recorded-live integration test pins the adapter's wire behavior. If any
   acceptance rate is materially below the current tier-1 model's, stop and
   report rather than re-seeding tiers.

7. **Add the delta pass.** Vocabulary revision adding `follow_up` to
   `AiPurpose` (reversible). Pure module: input is the latest attached brief
   and the newly attached brief; output is an updated five-slot brief plus a
   what-changed note; prompt and validation follow the existing extraction
   contracts. Tests are pure-function, no database.

8. **Wire the delta pass after attach.** In the event runner, when a cluster
   attaches to an event whose last observation is within
   `event_followup_window_days` (default 10, new setting), run the pass and
   write the delta onto the new observation row. Tests assert the window
   boundary, that the delta lands only on the new row, and that a failed pass
   leaves the attach intact — the delta is enrichment, never a gate.

9. **Build the Gemini batch client.** Submit a batch of chat requests as one
   job; poll; return results through the ordinary `ChatResponse` shape; raise
   `ModelUnavailable` when the job is rejected or exceeds its wait budget.
   Batch prices come from configuration, and cost rows record them exactly as
   real-time rows do. Fake-transport tests cover submit, poll, reject, and
   expiry.

10. **Route scheduled extraction and matching through the provider ladder.**
    Both scheduled stages shared the manual runner's old single-adapter
    construction; they now use the same routed construction, and the match
    stage runs the delta pass after a recent attach. **Amended 2026-08-29
    during Task 10:** wiring the batch client into the scheduler requires a
    batch-job persistence seam (submit this cycle, poll a later one) that this
    plan never designed, and the batch client from Task 9 exists and is tested
    without it. Rather than grow a schema mid-task, batch adoption is deferred
    to the Task 13 measurement: if trailing spend justifies it, batch wiring
    becomes its own planned item with its own migration. Manual runs stay
    real-time, as the design already required.

11. **Build the pre-group stage.** Pure module: group normalized signals by
    query rule group, publisher country code, and a configurable day window
    (default one day, at most two); rank representatives by official standing,
    credibility tier, then earliest sighted, with a stable UUID tiebreak.
    Tests cover grouping boundaries, the ranking order, and that a signal with
    no rule or no country forms its own group rather than being dropped.

12. **Store pre-groups and change selection.** Reversible revisions for
    `story_groups` and membership with `representative`/`deferred` roles and
    `open`/`resolved`/`expired` states. Classification selection excludes
    deferred members of open groups; group resolution and expiry (default 72
    hours) return them to selection. Everything ships behind
    `pregroup_enabled`, default false, with no code path that can attach a
    deferred signal to an event or count it toward the evidence score.
    Repository tests cover exclusion, return, expiry, and the flag off.

13. **Add the measurement gate.** `ai/spend.py` computes trailing 30-day spend
    from `ai_requests` plus per-purpose and per-provider breakdowns, exposed as
    a runner subcommand with counts-only output. Run it against the live
    database, record the figure and the resulting pre-group recommendation
    (enable or leave off) in the report. This task produces the decision; it
    does not flip the flag.

14. **Review, gate, and report.** Load `code-review`, then `verify-and-stop`.
    Run the real `corepack pnpm verify`, capture live proof for one discovery
    run (language operator visible in request parameters), one extraction run,
    and the spend figure, and write
    `docs/reports/<run-date>-subproject-o-report.md` with the actual outputs.
    Hand back to the planner. The worker does not mark `O` verified.
