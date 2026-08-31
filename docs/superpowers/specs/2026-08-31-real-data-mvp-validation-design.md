# Lean MVP Real-Data Validation Design

**Date:** 2026-08-31
**Status:** designed

## Goal

Run the existing EpiSignal pipeline over one bounded completed real-data window,
inspect its signals, events, observations, summaries, and public read surfaces,
and record evidence sufficient to decide whether the Lean MVP is ready.

## Scope

The run covers 2026-08-30T00:00:00Z through 2026-08-31T00:00:00Z where the
existing connectors support that window. It uses the existing GDELT query rules,
source ingestion, retrieval, deduplication, triage, extraction, geocoding, event
matching, and summarization stages. Raw candidates are capped at 200 and total
AI spend at $1.00 for this validation run.

Triage prefers `mistralai/mistral-small-24b-instruct-2501` for its first attempt
only. Existing fallback rungs remain available. Extraction, event-summary, and
event-match-judge routing remain unchanged.

## Evidence boundary

No database rows are edited manually. No production thresholds, GDELT queries,
source roster, model comparison system, embeddings, or public product surfaces
are added. A run failure is evidence and is recorded rather than hidden. The
report distinguishes unavailable live checks from checked behavior and retains
IDs, timestamps, source links, and model/cost ledger facts needed to audit each
claim without exposing secrets.

## Acceptance

- Focused test proves the first TRIAGE request uses Mistral Small 24B.
- One bounded real-data run records funnel counts through API/UI checks.
- Approximately 20 relevant and 20 filtered triage cases are inspected when
  available; approximately 20–30 accepted extractions and 10–15 summaries are
  inspected when available.
- Numeric facts, nulls, dates, locations, source spans, event decisions,
  observation history, summary provenance, and cost rows are evaluated.
- Report uses exactly one MVP verdict and names at most three top blockers.
- `corepack pnpm verify` and `corepack pnpm test:pipeline` pass with zero
  unexpected xfails.

## Stop and rollback

Stop the run before the next stage if the raw candidate cap or AI request/cost
guard would be exceeded, if a clear outbreak is confidently filtered, if
repeated invented epidemiological numbers appear, or if a false merge would
combine different outbreaks. Preserve all already-written evidence. Do not
delete or rewrite production rows; if the run must be abandoned, record the
failed stage and leave the idempotent backlog for a separately reviewed
follow-up.
