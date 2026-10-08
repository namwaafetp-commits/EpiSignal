# Handoff — Next MVP priority: real-data end-to-end surveillance validation

**Date:** 2026-08-30
**State:** next implementation item after F Lite; do not start in the F Lite
task.

## Objective

Run the complete EpiSignal surveillance pipeline on real incoming data and
evaluate the real signals, events, observations, and summaries it produces.

## Why this is next

The Lean MVP and F Lite are verified in code, but synthetic fixtures cannot
show whether retrieval, deduplication, matching, observation history, and
summaries behave correctly on live reporting. Real-data validation is the
highest-value next evidence before adding more product or benchmarking
infrastructure.

## Dependencies already satisfied

- The Lean MVP pipeline stages, conservative event matching, observation
  history, summaries, API/UI, and scheduler are on `main`.
- F Lite has committed triage/extraction fixtures and deterministic scoring, but
  it does not justify an automatic roster change.
- Provider keys, database access, and the scheduler's explicit run boundaries
  are the operational prerequisites to confirm before execution.

## Scope boundary

In scope is a bounded run of the existing pipeline against real incoming
reporting, inspection of produced signals/events/observations/summaries, and a
provenance-preserving evaluation report.

Out of scope is changing the production roster or routing, enabling embeddings
or BGE-M3, changing event thresholds, adding benchmark infrastructure, changing
GDELT retrieval, automatic model selection, or building new public surfaces.

## Relevant records

- [Roadmap](ROADMAP.md)
- [F Lite report](docs/reports/2026-08-30-f-lite-model-check-report.md)
- [Lean MVP architecture](docs/lean-mvp-architecture.md)
- [Post-merge reconciliation report](docs/reports/2026-08-30-post-merge-reconciliation.md)

## Start condition

Planner defines one bounded real-data validation run, its date window and
stop/rollback behavior, then creates a fresh task branch/worktree from the
latest `main`. Do not begin execution in this handoff task.

## Completion condition

The bounded run produces a report covering what real signals and events were
created, whether observation and summary provenance is intact, the failure
cases found, and the next corrective item; no production configuration changes
are made without separate review.
