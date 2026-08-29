# Sub-Project O Report — High-Efficiency Pipeline and Gemini Transition

**Date:** 2026-08-29
**Item:** `O` (Band 2)
**Worker session:** planner-designed in parallel with `M`, then built as
worker per the operator's instruction.
**Design:** `docs/superpowers/specs/2026-08-29-high-efficiency-pipeline-design.md`
**Plan:** `docs/superpowers/plans/2026-08-29-high-efficiency-pipeline.md`
**Origin:** [Issue #1](https://github.com/namwaafetp-commits/EpiSignal/issues/1)

## Verification gate

`corepack pnpm verify` at `48da153` on `main`, tree clean of `O` files: exit
code 0. Real output:

- Python tests: **905 passed, 1 warning** (`80.98s`)
- Web tests: **58 passed, 8 files**
- `ruff check` clean; `ruff format --check` clean
- `mypy` and `tsc` clean across 107 source files
- Generated-contract diff clean; Next.js production build succeeded

An earlier gate run at `aae2b7e` failed exactly one test — the migration-head
canary still pinned at the previous revision — and passed everywhere else;
the pin update is the commit this gate ran at.

## Live proofs, all performed this session

- **Migration chain**: `db:migrate` applied revisions `20260829_0010`
  (English query-rule deactivation) through `20260829_0013` (story groups)
  against the live database; `db:seed` then reported
  `diseases=29 sources=2 query_rules=62 filter_rules=12 ai_models=5
  country_aliases=75 gazetteer_places=208059`.
- **English-only discovery**: two runs. Before the seed deactivation fix:
  `rules=124 ... discovered=830` (both rule sets active — see "Traps" below).
  After: `rules=62 rules_failed=0 ... discovered=412 duplicate=45 rejected=1
  deferred=266 stored=79 needs_review=21 failed=0`. Volume halved exactly as
  the design projected.
- **Dedupe into the run**: `examined=173 primaries=144 duplicates=29 failed=0`.
- **Gemini extraction (Task 6)**: `classified=20 relevant=13 irrelevant=7
  extracted=13 review=0 unavailable=0 requests=23 stopped_early=False`.
- **Cost ledger for that run** (two-hour window):

  ```text
  google/gemini-3.5-flash-lite   classification accepted   n=1  cost=0.005578
  google/gemini-3.5-flash-lite   extraction     accepted   n=4  cost=0.009063
  google/gemini-3.5-flash-lite   extraction     rejected   n=9  cost=0.022782
  mistralai/mistral-small-24b-instruct-2501
                                 extraction     accepted   n=9  cost=0.001556
  total: $0.0390
  ```

- **Trailing spend (Task 13, the measurement gate)**:
  `window_days=30 requests=139 cost_usd=0.118554`.

## What was built

1. **Language enforced twice** — the GDELT client appends `sourcelang:eng`
   for English rules and drops mismatched entries; 62 seed rules pinned to
   `en`, unrestricted rows deactivated in both a revision and the seed loader.
2. **Provider as a roster fact** — `ai_models.provider` vocabulary
   (`openrouter`, `gemini`), reversible revision; a routed model dispatches
   each rung to its provider's adapter, so fallback is ordinary tier
   climbing across providers, with no fallback code.
3. **`GeminiChatModel`** — the one-method `ChatModel` boundary, structured
   output through a Gemini-dialect schema sanitizer, zero temperature,
   schema-less JSON fallback on a 400, `ModelUnavailable` semantics
   preserved, credentials never in exception strings.
4. **The delta pass** — after a cluster attaches to an event observed within
   `event_followup_window_days` (default 10), two briefs are compared
   (~300 tokens, no article re-read), the updated brief plus what-changed
   lands on the newest observation row, `follow_up` cost row written for
   every attempt. "Updated" stays derived: `last_updated_at` already moves.
5. **Batch client** — submit/poll against the v1beta batch API, per-entry
   answers with gaps as `None` (kept answers are never discarded), job-level
   failures as `ModelUnavailable`.
6. **Pre-group stage, default off** — pure grouping by rule group, publisher
   country, and day window; representative ranked by official standing,
   credibility, then earliest sighting; storage in `story_groups` with
   membership roles; classification selection excludes deferred members of
   open groups only; resolution and 72-hour expiry return them; a disabled
   stage still closes open groups so nothing is ever stranded; deferred
   signals are never evidence. `pnpm pregroup:signals` is operator-run —
   the stage is deliberately absent from the daily chain while the flag is
   off.
7. **Spend measurement** — `ai/spend.py` plus `pnpm spend:report`, trailing
   window from the ledger, per model/purpose/outcome breakdown.

## The measurement gate's decision

The trailing 30-day figure is **$0.1186** — already under the one-dollar
target with pre-group off and batch unwired. Per the design's stop condition:

- `pregroup_enabled` stays **false**. Nothing in the report justifies
  changing selection semantics to save money that is not being spent.
- Batch wiring stays deferred (Task 10 amendment in the plan): it needs a
  batch-job persistence seam that was never designed, and at current volume
  the discount is worth cents.

## Findings the operator should know

- **`gemini-2.5-flash-lite` is retired for new keys.** The live API returns
  404 pointing at `gemini-3.5-flash-lite`; the roster seed now activates
  3.5 at list prices **$0.30/$2.50 per million** (batch $0.15/$1.25,
  verified against the provider's pricing page). The proposal's
  $0.10/$0.40 assumption no longer exists; the cost model in the design
  already refused to adopt estimates, and the ledger confirms reality.
- **Gemini's extraction acceptance is poor; the ladder absorbed it.** In the
  validation run, 4 of 13 Gemini extractions were accepted; rejections were
  5 ungrounded (source spans not verbatim), 3 shape, 1 low-confidence. All
  9 rejects were accepted by tier-2 Mistral at $0.0016 — cross-provider
  fallback worked exactly as designed, and the wasted tier-1 spend
  ($0.0228/run at this volume) is visible in the ledger. Classification was
  100% accepted in one batched request. If this pattern holds over a week of
  runs, the honest next lever is tier-1 extraction prompt adherence for
  Gemini specifically, or demoting Gemini to classification only — a roster
  decision, no code.
- **Migration downgrade paths are written but not machine-tested** — there
  is no downgrade harness in the repository (no precedent exists either);
  downgrades were hand-verified against the live database for 0010's
  reactivation semantics only.

## Traps hit and closed

1. **Migrate-then-seed ordering**: revision 0010 deactivates `any` rows only
   when English rows exist, and the first live sequence seeded after
   migrating — both rule sets went active (`rules=124`). The seed loader now
   performs the same deactivation on every run, which is order-independent;
   the second discovery run proved it (`rules=62`).
2. **Roster rows vanish from attention**: dropping a model from the seed
   file does not deactivate its database row. Switching 2.5 for 3.5 left 2.5
   active and it sorted first, costing a 404 per climb. The seed now carries
   the retired row explicitly inactive, matching the DeepSeek precedent.
3. The stale `gemma-4-31b-it:free` rows in the ledger are historical (an
   earlier era's free ladder), confirmed inert in the live roster.

## Review

`code-review` ran as two parallel sub-agents (standards axis, spec axis)
against `b2b5f9d...HEAD`. All hard findings were fixed before the gate
(`aae2b7e`): dead `GroupRole` enum removed, naive-clock bug in the spend
window, all-or-nothing batch poll (now per-entry), deferral stranding on
flag flip (disabled stage now closes open groups), delta target now provably
the newest report, duplicated delta wiring extracted. Judgement calls
accepted and recorded: `story_groups` table naming versus the pre-group term
(storage names what it groups; the domain term lives in `CONTEXT.md`), batch
client unwired pending its own item, migration downgrade tests absent for
lack of any harness.

## Parallel-track integrity

`M` ran simultaneously on the same tree. Every `O` commit stages only `O`
files; `ROADMAP.md` and `STATUS.md` edits were split per hunk so the `M`
worker's uncommitted work was never swallowed. `HANDOFF.md` was never
touched. `M`'s two doc commits (`ef0ddc2`, `537202c`) appear in the review
range and were excluded from review scope.

## Hand back

All fourteen tasks ticked. Item `O` stays `building`; the planner verifies
and marks it. The two follow-up candidates the evidence names — Gemini
extraction prompt adherence, and batch wiring with its persistence seam —
are planner decisions, not worker scope.
