# PR #15 Flash-Brief Blocker Fixes

The three production blockers identified in the PR review are fixed in
implementation commit `edbba9e0d340ebacb36df7d394a97c0530a081ce`.

1. Scheduled GDELT retrieval now requires `processing_status=classified` and
   `public_health_relevant=true`; false, null, unavailable, guarded, and
   overflowed classification states do not retrieve.
2. Classification rejection leaves signals eligible for classification retry
   and no longer records extraction failure.
3. Classification requests use the structured classification schema, stable
   schema name, and temperature zero.
4. Extraction now captures grounded `response_actions` and
   `driver_or_barrier_evidence` primitives with source spans and indexes.
5. Observations persist validated material facts in the existing
   `20260901_0020_event_flash_brief` migration, and the event API exposes them.
6. Material-change tests cover epidemiological counts, geography, pathogen,
   transmission, response, driver evidence, unchanged facts, and time alone.
7. Summary tests use supplied evidence and cover absent response, absent
   driver, unsupported broader risk, and the unchanged flash-brief contract.
8. Repair dry-runs remain read-only while reporting in-memory `ai_requests` and
   `ai_cost_usd`; `--limit` and `--max-ai-requests` remain available.
9. Backend/API tests: `1273 passed, 2 warnings`.
10. Web tests: `105 passed` across 14 test files.
11. Pipeline-order gate: `18 passed`.
12. `corepack pnpm verify` passed formatting, lint, mypy, TypeScript, web tests,
    backend tests, contract freshness, and the optimized production build.
13. The implementation verification commit is
    `edbba9e0d340ebacb36df7d394a97c0530a081ce`; the final PR head is reported
    in the handoff after the completion-report commit.
14. Production data and production services were unchanged.
15. The production repair was not executed.
16. The scheduler was not enabled or changed.

The verification run emitted only the repository's existing Vite and Python
dependency deprecation warnings. No deployment or merge was performed.
