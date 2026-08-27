# GDELT Discovery Layer — Umbrella Architecture

**Date:** 2026-08-27
**Status:** Approved
**Depends on:** WHO DON and ECDC ingestion (merged to `main` on 2026-08-27)

## Purpose

This document fixes the shape of the whole GDELT layer so that each sub-project
can be designed, planned, and implemented on its own without the target moving.
It contains no implementation detail. Each sub-project has its own design
document.

## The product principle

GDELT is the radar, not a source of truth. It reports where to look; the
publisher's own page and, later, official reporting decide what is true.

A GDELT-discovered article may create an early signal. It may never, on its own,
create an officially confirmed outbreak. Only an appropriate official authority
can do that, and it does so through the existing official-source path.

## Position in the system

```text
OFFICIAL SOURCES                    GDELT + LOCAL NEWS
WHO / ECDC / CDC / MoH              high sensitivity
run_ingestion                       run_discovery
1 connector, 1 known source         1 connector, N discovered publishers
        │                                   │
        └───────────────┬───────────────────┘
                        ↓
                     SIGNALS
                        ↓
        filter → classify → extract → geocode
                        ↓
              deduplicate + cluster
                        ↓
             match or create EVENT
                        ↓
        official sources later corroborate,
        confirm, or update
```

Both paths write to the same `signals` table and share URL canonicalization,
content fingerprinting, and the storage boundary. They differ in how a publisher
is resolved, which is why they are separate pipelines rather than one
generalized pipeline.

## Sub-projects

Each is an independent spec, plan, and implementation cycle. The priority
numbers refer to the requirement document's section 31.

| ID | Sub-project | Priority items | Ends when |
| --- | --- | --- | --- |
| A | Discovery connector, query library, provenance schema | 1–3 | A GDELT-discovered signal is stored with its real publisher, original URL, and separated timestamps. |
| B | Stage 0: deduplication and rule filtering | 4–5 | Syndicated copies and obviously irrelevant articles are rejected before any AI call. |
| C | AI: batched classification, extraction, escalation, cost logging | 6–8, 23 | Relevant signals carry schema-validated epidemiological extraction, and every AI request is costed. |
| D | Story clustering, event matching, dual scoring | 9–12 | Signals group into story clusters, clusters match or create events, and early-signal and evidence scores are computed separately. |
| E | Signal Radar API, Signal Radar UI, admin monitoring | 13–15 | A user sees an early signal, its uncertainty, and can open the original article. |
| F | Model benchmarking harness | 28 | Free-model selection is backed by stored measurements rather than impressions. |

Sub-project A is designed in
`docs/superpowers/specs/2026-08-27-gdelt-discovery-design.md`.

## Invariants every sub-project must hold

These are the constraints that later work is not permitted to relax.

**Provenance.** The publisher is the source. `discovered_via` records that GDELT
found the article. No article is ever labelled "Source: GDELT". The original URL
is preserved and remains openable by a user at every stage.

**Timestamps are never conflated.** `published_at`, `first_seen_at`,
`retrieved_at`, and `gdelt_seen_at` are distinct columns with distinct meanings.
`event_date` and `data_as_of_date`, when stated, are distinct again. A missing
timestamp is stored as NULL and displayed as unavailable; it is never
substituted from another column.

**Cheap before expensive.** Deterministic checks run before network fetches, and
network fetches and deterministic filters both run before any AI call. Cost
grows down this ladder and so must the volume reaching each rung.

**Two scores, never merged.** `early_signal_score` answers how interesting a
signal is for surveillance. `evidence_score` answers how strongly it is
supported. A local newspaper report can be 92 and 38 at once. Collapsing them
into one number destroys the distinction the product exists to make.

**Confirmation is earned, not inferred.** A GDELT-only signal begins at
`signal` or `monitoring`. It advances through corroboration by independent
reporting and then by health authorities. `officially_confirmed` requires an
official source, and no AI confidence value can grant it.

**Conservative matching.** False merging of two events is worse than carrying a
temporary duplicate. Matching weights and thresholds stay configurable, and the
ambiguous band escalates rather than guesses.

**AI confidence is not calibrated.** A model's self-reported confidence is one
input among rule consistency, source quality, and cross-source corroboration.
It is never the sole basis for a processing decision.

**Failures stay visible.** Every signal carries a processing state. Nothing
fails silently, and every failure is reachable from the admin view.

**Official provenance is only added to.** No sub-project removes or rewrites the
existing official-source columns, relationships, or observation history.

## Cost posture

Phase 1 targets roughly 90–95 percent of AI workload on free OpenRouter
inference, 5–10 percent on a low-cost paid Gemini model, and rare use of a
stronger GPT model, for an approximate spend of 0–5 USD per month.

This is a target, not a constraint that outranks correctness. Where free-model
performance proves inadequate, sub-project C escalates selectively and records
the cost rather than accepting a wrong answer.
