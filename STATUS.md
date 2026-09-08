# Status — where the build is right now

The long roadmap is in [ROADMAP.md](ROADMAP.md). The planner/worker contract is
in [docs/agents/workflow.md](docs/agents/workflow.md). This file is the current
position and evidence ledger.

**Last updated:** 2026-09-02

## Position

| Field | Value |
| --- | --- |
| Band | 2 — GDELT discovery layer |
| Item | Final simplified three-model surveillance pipeline |
| Status | `building` |
| Briefing | [HANDOFF.md](HANDOFF.md) |
| Spec | [Lean MVP real-data validation design](docs/superpowers/specs/2026-08-31-real-data-mvp-validation-design.md) |
| Plan | [Lean MVP real-data validation plan](docs/superpowers/plans/2026-08-31-real-data-mvp-validation.md) |

## Verified main baseline

The current `main` baseline commit is
`cda5efe120ab92fe42f051928df1acbe6cc1c228`. The following commands were run
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

F Lite final verification passed with 95 web tests, 1193 Python tests, and 0
xfails; `test:pipeline` passed with 16 tests; the offline model-check suite
passed 9 tests. Live triage evidence is stored in `benchmarks/results/`;
extraction live smoke was attempted but timed out and is explicitly recorded as
`not_run`. See the [F Lite report](docs/reports/2026-08-30-f-lite-model-check-report.md).

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

## Task ledger — `F Lite`

- [x] Twenty triage and twenty extraction cases are committed separately from
  production data.
- [x] Deterministic triage and extraction scoring exposes false negatives,
  grounding failures, unsupported numeric claims, null handling, cost, and
  latency without an LLM judge.
- [x] Explicit capped provider calls and JSON result persistence are isolated
  from production routing and the production AI ledger.
- [x] Offline suite and full repository gates pass; bounded live triage evidence
  is recorded. Live extraction evidence remains an explicit follow-up because
  the provider smoke timed out.

## Task ledger — real-data end-to-end surveillance validation

- [x] Make Mistral Small 24B first for TRIAGE only, with fallback and adjacent
  purpose routing unchanged.
- [x] Run one bounded 2026-08-30 to 2026-08-31 UTC real-data window under the
  200-candidate and $1.00 AI caps.
- [x] Inspect real triage, extraction, event matching, observation history,
  summaries, provenance, and API/UI surfaces.
- [x] Write `docs/reports/2026-08-31-real-data-mvp-validation.md` with funnel,
  quality, cost, verdict, deviations, and no more than three blockers.
- [x] Run `corepack pnpm verify` and `corepack pnpm test:pipeline`; record exact
  outputs and zero unexpected xfails.

## Verified validation baseline

The real-data validation code and report were verified on this branch. The
verification commit is `a79b249b71f66485bd29b6901baa9ba50b9046c8` and contains
the summary JSONB fix, event-detail regression test, and updated evidence.

| Fact | Value |
| --- | --- |
| `corepack pnpm verify` | PASS; 95 web tests, 1,198 Python tests, 0 xfails |
| `corepack pnpm test:pipeline` | PASS; 16 tests, 0 xfails |
| MVP verdict | `MVP READY WITH MINOR FIXES`; see validation report |

## Post-merge project state

Lean MVP real-data validation: COMPLETE

MVP verdict: MVP READY WITH MINOR FIXES

## Verified baseline — Lean MVP branch reconciliation

The branch baseline reconciliation was verified at commit `ad26140` with
`corepack pnpm verify`: 1,222 Python tests and 105 frontend tests passed, with
two existing dependency deprecation warnings. The completion report is
[the Lean MVP test reconciliation report](docs/reports/2026-08-31-lean-mvp-test-reconciliation-report.md).

Post-MVP follow-up only: one GDELT rule may intermittently return
`GdeltUnavailable`, triage precision can improve later, and extraction
benchmarking remains deferred. Model benchmarking, extraction benchmarking,
event matching thresholds, embeddings, and GDELT query redesign are not being
reopened.

## Other roadmap state

- `D2b` is verified for the Lean MVP's LLM-judge scope; embeddings are deferred
  to Phase 2.
- `E`, `L`, `M`, and `O` are verified. `G` and `I` are also implemented and
  verified through the R events API/UI work.
- `H`, `J`, `K`, `N`, and `Z` remain not-started. F Lite and real-data
  end-to-end surveillance validation are verified; only residual follow-up
  risks remain for this validation item.

## Next action

Review and push the focused test-migration commit on
`codex/final-three-model-pipeline`; production model-roster updates remain a
separate authorized operation.

## Blockers

The implementation still needs planner handoff before the roadmap item is
marked `verified`; the full gate is now green. See [the final pipeline
report](docs/reports/2026-09-02-final-three-model-pipeline-report.md).

## Task ledger — final simplified three-model pipeline

- [x] DeepSeek V4 Flash relevance classification over discovery metadata only.
- [x] Gemini 3.1 Flash-Lite identity extraction with one same-model repair.
- [x] Deterministic disease/location normalization and exact multi-location grouping.
- [x] Mistral Small 3.2 summary wiring over linked clean article sources.
- [x] API/dashboard observation and multi-location surface updated; legacy rows retained.
- [x] Focused acceptance, lint, type, contract generation, and web build checks passed.
- [x] Full `corepack pnpm verify` gate: 1,188 Python tests passed, 1 skipped,
  107 web tests passed, and 2 existing deprecation warnings.

## Task ledger — deterministic Telegram monitoring (2026-09-07)

- [x] Reuse the existing read-only HealthSummary evaluation and preserve its semantics.
- [x] Add deterministic daily, abnormal, and recovery formatters plus safe Telegram transport.
- [x] Persist observed state and delivery checkpoints; suppress duplicates and retry failed sends.
- [x] Integrate monitoring-only CLI modes; document proposed UTC/ICT cron and durable mount.
- [x] Resolve independent standards/specification review findings with regression tests.
- [x] Full repository gate passed: 107 web tests; 1,418 Python tests passed, 2 skipped.
- [x] Focused monitoring/notification suites: 138 passed; lint, format, types, contracts, build passed.

The tested implementation tree is committed as
`a053e19af26440df819e447a0297e601ea20d1fb`. The current expected Alembic head
remains `20260904_0022`; no production migrations or deployment were performed.
Two PostgreSQL tests remain skipped without `EPISIGNAL_TEST_DATABASE_URL`.
The existing web marker test received a test-only clock correction; map code
and all monitoring health semantics are unchanged.

Completion evidence and review points:
[Telegram monitoring report](docs/reports/2026-09-07-telegram-monitoring-report.md).
Next action: review the commits and proposed notification configuration/schedule.
**NOT DEPLOYED.** Final push confirmation is recorded in the task response.

## Task ledger — local Telegram cadence correction (2026-09-07)

- [x] Reproduce routine hourly freshness WARNING/recovery cycles with five-minute polling.
- [x] Document post-run evaluation plus independent :16/:26 watchdog proposal.
- [x] Separate daily primary/retry at 08:20/08:21 ICT (01:20/01:21 UTC).
- [x] Keep SQLite implementation and one-second timeout; test contention in both modes.
- [x] Label production assumptions and all scheduler entries as unverified proposals.
- [x] Independent standards and specification reviews: no actionable findings.
- [x] Local gate: 1,432 Python tests passed, 2 skipped, 2 warnings; 107 web tests passed.
- [x] Backend suite: 1,360 passed, 2 skipped; monitoring/notification suites: 150 passed.

No runtime source, monitoring semantics, thresholds, AI, surveillance behavior,
production configuration, or migrations changed. Alembic head: `20260904_0022`.
Evidence: [cadence correction report](docs/reports/2026-09-07-telegram-cadence-correction-report.md).
Next action: separate deployment-time verification of actual scheduler phase,
runtime, wrapper, container, timezone, environment, and persistent mount.
**NOT DEPLOYED. VPS NOT ACCESSED. COOLIFY NOT ACCESSED. PRODUCTION CRON NOT MODIFIED.**

## Task ledger — additive surveillance dimensions and flexible summaries (2026-09-08)

- [x] Map all 30 seeded diseases to the explicit additive disease-group taxonomy with unknown fallback.
- [x] Add nullable DeepSeek host-sector classification, deterministic event derivation, persistence, filters, and UI labels.
- [x] Add strict flexible Mistral summaries with 3–5 bullets while preserving legacy summary rendering.
- [x] Expose additive API/contracts and persist flexible summary payloads in event and summary history.
- [x] Run the full repository gate: 117 web tests, 1,458 Python tests, 2 skipped, lint, format, types, contracts, and build passed.

Completion evidence: [surveillance dimensions and flexible summaries report](docs/reports/2026-09-08-surveillance-dimensions-and-flexible-summaries-report.md).
Commit: `bb7aaeb`. Local only; no production migration or deployment was performed.

## Review corrections — surveillance dimensions (2026-09-08)

- [x] Unknown filters include unmapped canonical disease slugs.
- [x] `/events` filter links preserve combined query parameters and clear only the active filter.
- [x] New Mistral responses require only the flexible 3–5 bullet contract; legacy rows remain readable.
- [x] Flexible homepage summaries omit the legacy risk block while historical summaries retain compatibility.
- [x] Review correction gate passed: 125 web tests, 1,460 Python tests, 2 skipped, contracts, and build passed.

Evidence: [surveillance review corrections report](docs/reports/2026-09-08-surveillance-review-corrections-report.md).
Fix commit: `bc51db3`; migration head remains `20260908_0023`.
