# Handoff — Item F: Model benchmarking harness

**Date:** 2026-08-30
**Item:** `F` — Model benchmarking harness
**State:** `not-started`; no F-specific design spec or implementation plan is
committed.
**Role:** planner first, then implementation worker after the design and plan
are approved.

## Objective

Build a reproducible harness that stores comparable acceptance rate,
cost-per-accepted result, grounding rate, and five-slot brief quality by model
and purpose, so free-model selection is backed by measurements rather than
impressions.

## Why this is next

The Lean MVP now has purpose-scoped provider seams, structured validators,
grounding checks, the AI cost ledger, an ambiguous-event judge, and an event
summarizer, but it does not yet retain a durable cross-model comparison. F is
the remaining prerequisite for evidence-based model or roster decisions.

## Dependencies already satisfied

- `C` and `C2`: structured extraction, grounding, English title, and five-slot
  brief contracts are implemented and covered by tests.
- `O`: provider adapters, purpose-scoped model routing, and cost rows exist.
- `O2`: the title gate, retrieval, pre-grouping, and cluster extraction funnel
  are verified on `main`.
- `R`: conservative event matching, the judge, observations, summaries, and
  the synthetic pipeline fixture are verified on `main`.
- `M` and `L`: review recovery and scheduled stage boundaries are verified.

## Scope boundary

In scope is the benchmark data model, deterministic fixture/corpus inputs,
measurement protocol, stored results, and reports needed to compare existing
models by purpose.

Out of scope is changing the production roster or routing, enabling embeddings
or BGE-M3, wiring batch jobs, changing event thresholds, running the live
scheduler, resolving live review cases, and building new public product
surfaces. Do not change the Lean MVP architecture while measuring it.

## Relevant records

- [Roadmap item F](ROADMAP.md)
- [GDELT layer architecture](docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md)
  — defines F as the model benchmarking harness.
- [AI extraction design](docs/superpowers/specs/2026-08-27-ai-extraction-design.md)
  — defines the extraction, grounding, and validation signals a benchmark must
  measure.
- [Lean MVP architecture](docs/lean-mvp-architecture.md) — authoritative
  runtime direction and model-purpose boundaries.
- [Post-merge reconciliation report](docs/reports/2026-08-30-post-merge-reconciliation.md)
  — current baseline and verified dependencies.

## Start condition

Design F against the latest `main`, commit the F-specific spec and plan, and
only then create a fresh task branch/worktree from that `main`. No historical
branch or stale worktree is a valid base. Do not implement F in this handoff
task.

## Completion condition

The F plan is fully implemented, benchmark results are stored with provenance
and cost, the comparison is reproducible without production side effects,
`corepack pnpm verify` is green, and a completion report records the actual
measurements and remaining uncertainty.
