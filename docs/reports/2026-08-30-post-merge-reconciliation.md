# Post-Merge State Reconciliation Report

**Date:** 2026-08-30
**Baseline commit:** `1b6371340e58f6773766f6920a47279a87f8bc0d`
**Scope:** Documentation reconciliation after PR #2; no product code changes.

## Verification

The baseline was checked from local `main`, which matched `origin/main`:

| Check | Result |
| --- | --- |
| `corepack pnpm verify` | PASS |
| Web tests | 95 passed |
| Python tests | 1184 passed |
| Xfails | 0 |
| Migration head | `20260830_0019` (`20260830_0019_event_summaries`) |
| `corepack pnpm test:pipeline` | PASS; 16 passed |

The verification emitted the repository's existing deprecation warnings but no
test failures or unexpected xfails.

## Reconciled state

`O2` is implemented and verified by the current code and tests. Its keyword
gate, deferred retrieval, pre-grouping seam, cluster extraction, grounded
member citations, and spend reporting are present on `main`. The historical
live-proof step was waived; it is not represented as completed live evidence.

`R` is implemented and verified for the superseding Lean MVP scope. The daily
chain uses RapidFuzz deduplication, deterministic conservative matching, the
ambiguous-band LLM judge, additive observations, versioned summaries, and the
events API/UI. Embeddings and BGE-M3 remain dormant Phase-2 scaffolding and are
not part of the default daily runtime.

The earlier `2026-08-30-lean-mvp-report.md` is retained as historical evidence
from the pre-merge implementation pass. Its test counts and interim xfail are
not the current baseline above.

## Next implementation item

`F` — Model benchmarking harness. The provider seams, purpose-scoped AI roster,
cost ledger, extraction validation, event judge, and event summarizer are now
available; the missing capability is durable, comparable quality and cost
measurements by model and purpose. No committed F-specific spec or plan exists
yet, so design and planning precede implementation.
