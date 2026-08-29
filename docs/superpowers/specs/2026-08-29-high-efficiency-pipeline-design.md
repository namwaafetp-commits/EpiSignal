# High-Efficiency Pipeline and Gemini 2.5 Flash-Lite Transition — Design

**Date:** 2026-08-29
**Origin:** Operator architecture proposal, filed as GitHub issue #1.
**Status:** Approved for planning.
**Depends on:** `C2` (brief shape), `D2a` (event attach seam), `L` (scheduler). All verified.

## Problem

The pipeline spends as if every non-duplicate signal deserved a full extraction
through paid tiers, in every language GDELT returns, with no event-level memory
of what a follow-up article changed against the last report. The operator's
target is a measured monthly AI spend under one US dollar, with the spend read
from the `ai_requests` ledger rather than estimated.

## Non-goals

Phase 2 multilingual ingestion (the English restriction must be a reversible
toggle, not a structural change). Replacing `D2b`'s embedding escalation.
Any new public UI. Forecasting, alerts, accounts — standing Phase 1 non-goals.

## What the code says today

These facts were read from the tree before this design was written, and every
decision below is made against them:

- `QueryRule.language` is stored, seeded as `any`, and never applied. The GDELT
  DOC 2.0 client sends `rule.query` verbatim; the API's `sourcelang:` operator
  is unused, and results are not filtered by language after the fact.
- The dedupe gate collapses syndicated copies on title and body similarity, and
  its primary choice is earliest-sighted, explicitly not credibility-ranked,
  because every GDELT-registered publisher starts as unknown.
- `D2a` already clusters extracted signals, matches clusters against candidate
  events inside a configurable recency window (default 90 days), attaches,
  creates, or refuses conservatively, and appends observations. An event's
  `last_updated_at` already moves when a follow-up attaches; the radar already
  ranks by recency. There is no event-level record of *what changed*.
- The model roster is a database table (`ai_models`): tier, model id, label,
  prices, active. It carries no provider. `extract_runner` constructs one
  OpenRouter adapter and hands it to both passes; the ladder protocol was
  designed so one adapter serves the whole ladder.
- Every request, answered or not, writes a cost row with the prices in force at
  the moment of the call.

## Cost model, stated honestly

The proposal's figures are optimistic and are not adopted as claims. Working
arithmetic from Flash-Lite list prices, recorded here so the plan can replace
it with measurements:

- English-only filtering halves discovery volume (GDELT reports roughly 50%
  English), before any other lever.
- At ~225 extractions/day after that halving, real-time Flash-Lite is on the
  order of a few US dollars per month, not cents.
- Pre-AI story grouping (one to two extractions per story per window) brings
  that to roughly 40–70 extractions/day, an estimated sub-dollar month.
- The batch API's fifty-percent discount applies on top.

Conclusion: all four levers — language, provider, batch, grouping — are needed
for the stated target, and the target itself is only ever *confirmed* from the
`ai_requests` ledger. Nothing in this design treats an estimate as a result.

## Decision 1 — English-first discovery is enforced twice

The query-rule language becomes real in both directions:

1. **At the API**: when a rule's language is not `any`, the client appends the
   GDELT `sourcelang:<code>` operator to the query it sends.
2. **At the result**: entries whose reported language does not map to the
   rule's language are dropped and counted, the same quiet guard the locale
   tables already practice for unmappable names.

Seeds move every rule to `language: "en"`. Because the query-rule natural key
is `(query, language)`, pinning English creates *new* rows; the same seed
revision deactivates the `any` rows so both are never active at once. Phase 2
multilingual ingestion is then a seed and activation change, nothing more.

## Decision 2 — the provider becomes a roster fact, the ladder stays one ladder

`ai_models` gains a `provider` column with a closed vocabulary (`openrouter`,
`gemini`). The rung resolution changes from "one adapter for the ladder" to
"the adapter the rung's provider names": the runner constructs a small map of
adapters and the ladder asks for spec-plus-adapter per rung.

The transition itself is then a seed change with a code change underneath it:

- **T1** becomes `google/gemini-2.5-flash-lite` at Gemini list prices,
  provider `gemini`.
- **T2/T3** stay on OpenRouter unchanged. Outage fallback is the ladder
  climbing, exactly the mechanism that already exists — no new fallback code.

A new `GeminiChatModel` implements the existing `ChatModel` boundary: one
`complete` method, structured output from the same response-schema contracts
the passes already build, temperature zero. It raises the protocol's existing
`ModelUnavailable` for refusals, timeouts, and quota, so signals stay
selectable rather than being sent for review — the ladder's existing contract.

The OpenRouter key stays configured; a Gemini key is added beside it. A rung
whose provider key is missing is skipped with `NoModelsConfigured` semantics
preserved: the ladder shortens rather than the run failing.

## Decision 3 — follow-up is a delta pass after attach, not a pipeline reorder

The proposal's follow-up design (feed the previous brief into the extraction of
a new article) requires knowing the event before extraction, which the chain
cannot do: disease and place are *outputs* of extraction. The design rejects
that reorder and uses what `D2a` already provides:

1. A new cluster attaches to an existing event, as today.
2. If the event's last observation is within a configurable follow-up window
   (default 10 days), a **delta pass** runs: a cheap model call whose input is
   the latest attached brief plus the newly attached brief — roughly three
   hundred tokens, no article re-read — and whose output is an updated
   five-slot brief plus an explicit what-changed note.
3. The delta lands on the new observation row. Observations remain appended,
   never overwritten; the pass adds a summary to the newest row and rewrites
   nothing behind it.

`AiPurpose` gains a `follow_up` value (vocabulary migration). "Updated" is
**derived, never stored**: an event is current exactly when its
`last_updated_at` is recent, which the radar already orders by. No boolean
column, no new verification-status vocabulary.

## Decision 4 — pre-grouping extends the dedupe philosophy, it does not compete with D2a

A **pre-group** is a bounded, pre-AI grouping of `normalized` signals by the
only disease and place facts that exist before extraction: the query rule's
group (the query library is disease-keyed), the publisher's country, and a
one-to-two-day window. Per group:

- One **representative** proceeds to classification and extraction.
- The rest become **deferred**: they keep their rows, their publisher, and
  their place in history, and they are simply not selected while their group is
  open.

Two boundaries keep this honest, and they are the heart of the design:

- **Deferred signals do not become evidence.** Attaching unextracted signals to
  events would let keyword coincidence masquerade as corroboration. The
  evidence score keeps counting only signals that were independently judged
  relevant and extracted. Skipping a signal deletes nothing; attaching one
  unverified would invent something.
- **Deferral is temporary and bounded.** When the representative is extracted
  (relevant or not) or when the group expires (default 72 hours), every
  deferred signal returns to normal selection. Nothing is permanently unseen.

Representative choice ranks official publishers and higher credibility tiers
first, then earliest sighted. In practice GDELT publishers start unknown, so
the earliest-sighted rule will dominate — the same conservatism the dedupe
gate already documents. The ranking exists so the preference becomes true as
source standing accumulates, without another change here.

Storage: a `story_groups` table with rule group, country, window, state
(`open`, `resolved`, `expired`), and a membership table linking member signals
with a `representative`/`deferred` role. No new `ProcessingStatus` value —
deferral is membership, not a processing state, so the status vocabulary stays
closed and every existing reader keeps its meaning.

This phase ships behind a default-off configuration flag. Whether it is turned
on is decided by measurement, not by this document: after the earlier phases
are live, the trailing spend read from `ai_requests` either justifies the
flag or it stays off. That is the stop condition.

## Decision 5 — batch mode is a scheduler concern with a real-time floor

After real-time Gemini extraction is validated live, scheduled extraction runs
gain a batch path: requests are collected and submitted as one Gemini batch
job; a later poll in the same scheduler cycle retrieves results and writes
them through the ordinary acceptance path, cost rows included at batch prices.
If the batch job is unavailable, rejected, or still pending after its budget,
the affected signals fall back to real-time in the same run. Batch never
leaves signals stranded: a request either returns through acceptance or
re-selects for real-time.

Real-time stays the path for manual and high-priority single-article runs.

### Measurement amendment, 2026-08-29

Task 10 proved that a safe scheduled batch path needs durable batch-job state:
one scheduler cycle submits work and a later cycle polls it. This design had not
specified that persistence seam, so adding it during implementation would have
been an unreviewed schema expansion. The worker delivered and tested the batch
client, then deferred scheduler wiring to the measurement gate recorded in
Task 13 and the completion report.

The operator set the current target at `$0.50/month`. Measured trailing spend
was `$0.118554` at the worker gate and `$0.174529` after the planner's reordered
roster proof, both below target with pre-group disabled and batch unwired.
Therefore Decision 5's scheduler wiring is conditional future work, not an `O`
completion requirement: it begins only after measured spend exceeds target and
after a separate design defines batch-job persistence, recovery, and replay.
The built/tested client remains the reusable transport seam. This amendment
also preserves the original real-time floor and never strands signals.

## Invariants preserved

- Evidence provenance, conservative matching, observation history, source
  traceability, patient privacy — untouched by every decision above.
- The cost ledger records every request at the prices in force, batch
  included; the monthly figure is always a query, never a claim.
- Vocabulary changes are migrations with reversible downgrades; the query-rule
  seed change deactivates rather than deletes, so rollback is reactivation.
- Failure posture unchanged: stages log counts and exception types, never
  prompts, keys, or article text.

## Testing shape

- GDELT language enforcement: client tests asserting the operator is appended
  and mismatched entries are dropped and counted.
- `GeminiChatModel`: fake-transport contract tests (structured output, zero
  temperature, `ModelUnavailable` on refusal/timeout/quota), plus one
  recorded-live integration test over the ten-to-twenty-article validation set.
- Delta pass: pure-function tests over brief pairs; attach-path tests assert
  the observation row carries the delta and that nothing behind it moved.
- Pre-group: pure grouping and representative-ranking tests; repository tests
  assert deferred signals are invisible to selection and reappear on
  resolution and expiry.
- Batch: submit/poll cycle against fakes, including the fallback path.
- The gate is `corepack pnpm verify`, output quoted in the report.

## Live validation prerequisite

The Gemini validation task needs `EPISIGNAL_GEMINI_API_KEY` on the machine,
exactly as the OpenRouter key once blocked `extract`. The task records it as a
configuration prerequisite if absent, the same way STATUS.md recorded the
OpenRouter blocker.
