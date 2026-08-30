# Status — where the build is right now

The long roadmap is in [ROADMAP.md](ROADMAP.md). The planner/worker contract is
in [docs/agents/workflow.md](docs/agents/workflow.md). This file is the current
position and evidence ledger.

**Last updated:** 2026-08-30

## Position

| Field | Value |
| --- | --- |
| Band | 2 — GDELT discovery layer |
| Item | `F` — Model benchmarking harness |
| Status | `not-started` |
| Briefing | [HANDOFF.md](HANDOFF.md) |
| Spec | No F-specific spec is committed; design is the next planning step |
| Plan | No F-specific plan is committed |

## Verified main baseline

The current `main` commit is
`1b6371340e58f6773766f6920a47279a87f8bc0d`. The following commands were run
from that checkout on 2026-08-30 before this documentation reconciliation:

| Fact | Value |
| --- | --- |
| `corepack pnpm verify` | PASS |
| Web tests | 95 passed |
| Python tests | 1184 passed |
| Xfails | 0 |
| Migration head | `20260830_0019` (`20260830_0019_event_summaries`) |
| `corepack pnpm test:pipeline` | PASS; 16 passed |
| Lint, format, types, contracts, build | PASS |

The run emitted two existing Python deprecation warnings and the existing Vite
configuration warnings. No test failure or unexpected xfail occurred. The
full record is in
[the post-merge reconciliation report](docs/reports/2026-08-30-post-merge-reconciliation.md).

## Current implementation state

`O2` is complete and verified for its implemented code/test scope. The title
keyword gate, deferred retrieval, pre-grouping seam, cluster extraction,
member-specific grounding, and spend reporting are on `main`. The historical
live-proof step was waived and is not claimed as live evidence.

`R` is complete and verified for the superseding Lean MVP scope. The pipeline
has RapidFuzz near-exact deduplication, conservative deterministic matching,
an ambiguous-band LLM judge, additive observation history, material-change
summary updates, versioned event summaries, and the public events API/UI.
`StageName.EMBED` is excluded from `DAILY_CHAIN`; BGE-M3 and pgvector remain
dormant Phase-2 scaffolding.

The original O2 and R specs/plans and the earlier implementation report remain
historical records. The earlier report's interim test counts and xfail are not
the current baseline.

## Task ledger — `O2`

The original 19-task plan is preserved at
[the O2 plan](docs/superpowers/plans/2026-08-29-pipeline-funnel-v2.md). Its
implementation tasks 1–17 are present in the code and covered by the current
test suite:

- [x] Tasks 1–17: title gate, `filtered` status, deferred retrieval,
  pre-grouping, cluster extraction, member-specific grounding, fallback,
  spend reporting, and documentation/ADR code changes.
- [ ] Tasks 18–19 live proof and the original completion handoff were waived;
  no live result is represented as completed evidence. The code/test state is
  recorded in the [post-merge reconciliation report](docs/reports/2026-08-30-post-merge-reconciliation.md).

## Task ledger — `R` Lean MVP

The original 26-task plan remains historical. The following is the reconciled
ledger against the superseding Lean MVP architecture:

- [x] Tasks 1–8: early structured metadata, triage contract/pass, and the
  pre-fetch dedup path.
- [x] Tasks 9–16: embedding migration/provider/pass scaffolding, deterministic
  blocking, additive similarity, decision logging, and calibration fixtures.
  Embeddings are explicitly deferred; `EMBED` is not in `DAILY_CHAIN`.
- [x] Tasks 17–21: summary history, contract, representative-source picking,
  material-change detection, and the DeepSeek summary pass.
- [x] Task 22 Lean MVP replacement: summarize stage and runner are wired with
  idempotent material-change selection; the old force-flag requirement is not
  part of the Lean MVP.
- [x] Task 23: summary/judge requests are written to the existing cost ledger.
- [x] Task 24 Lean MVP replacement: architecture, implementation note,
  configuration, and ADR-level decisions are documented; the old standalone
  `news-event-pipeline` document is not part of this scope.
- [x] Task 25 Lean MVP replacement: the synthetic fixture invokes production
  deduplication, matching, event finalization, and observation logic at fake
  model boundaries; summary behavior is covered by the calibration tests.
- [x] Task 26 code/test gate: review corrections, current full verification,
  and the zero-xfail pipeline gate are complete and recorded in the
  reconciliation report.
- [ ] The original plan's live production proof was not run and is not claimed
  as synthetic/code verification evidence.

## Other roadmap state

- `D2b` is verified for the Lean MVP's LLM-judge scope; embeddings are deferred
  to Phase 2.
- `E`, `L`, `M`, and `O` are verified. `G` and `I` are also implemented and
  verified through the R events API/UI work.
- `H`, `J`, `K`, `N`, and `Z` remain not-started. `F` is the one next
  implementation item; no other item is active.

## Next action

**Planner:** design and plan `F` — Model benchmarking harness. Start from the
latest `main` in a fresh task branch/worktree when implementation begins. Do
not use historical branch names or stale worktrees as a base.

F's objective is to persist comparable acceptance, cost-per-accepted,
grounding, and brief-quality measurements by model and purpose. Its existing
dependencies (`C`, plus the verified purpose-scoped roster, cost ledger,
extraction validators, event judge, and summarizer) are satisfied. It must not
change the production roster or routing, wire batch jobs, enable embeddings, or
build new product surfaces. No F-specific spec or plan exists yet; the
benchmark design must be committed before implementation.

## Blockers

None. The known live-proof limitation is historical validation scope, not a
blocked implementation dependency.
