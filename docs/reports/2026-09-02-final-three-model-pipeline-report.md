# Final simplified three-model pipeline test-migration report

## 1. Failure classification

The fresh pre-migration run at `83b5793` had 152 failures (the handoff said 155). Classification before fixes: 147 LEGACY_TEST, 5 COMPATIBILITY_BUG, and 0 REAL_REGRESSION. Legacy failures asserted retired rich extraction fields, batch/fallback, judge/delta, count-observation, radar, pre-group, or stale harness behavior. Compatibility cases covered historical extraction/API readability and null-disease identity; they were resolved in test fixtures and assertions without production redesign. No new-pipeline defect was found.

## 2. Changes

Relevance, extraction, prompt, schema, validator, repository, summary, matching, clustering, assembly, score, runtime, radar, review, and API tests were migrated to the active contract. Retired calibration/judge/pregroup/delta-only tests were removed or replaced with deterministic calibration coverage. New tests cover one DeepSeek relevance request, Gemini identity repair, town-to-country containment guidance, publisher geography exclusion, exact disease IDs, exact location/time matching, article-grounded summary evidence, material-change behavior, legacy extraction/summary/observation reads, and API query bounds. Production files, schemas, migrations, schedulers, and integrations were not changed.

## 3. Final verification

Focused final-pipeline tests: 50 passed. Backend full suite: 1,188 passed, 1 skipped, 2 warnings. Frontend: 107 passed. Ruff: passed. Mypy: passed. Frontend typecheck: passed. Contracts: passed. Build: passed. `corepack pnpm verify`: passed. `git diff --check`: passed.

## 4. Git

HEAD before: `83b5793`. HEAD after: migration commit on `codex/final-three-model-pipeline`. Commit: `Align tests with simplified three-model pipeline`. Branch: `codex/final-three-model-pipeline`. Pushed: true after the authorized branch push.

## 5. Pipeline integrity

Relevance = DeepSeek V4 Flash (`deepseek/deepseek-v4-flash-0731`). Extraction = Gemini 3.1 Flash-Lite (`google/gemini-3.1-flash-lite`). Extraction fields = disease + `locations[{town,country}]` only. Grouping = deterministic exact identity/location/time rules. Summary = Mistral Small 3.2 (`mistralai/mistral-small-3.2-24b-instruct`) from linked source articles.

## 6. Production safety

production_rows_changed=0
migration_applied=false
deploy=false
merge=false
scheduler_changed=false
scheduler_off=true
production_model_registry_changed=false
requeue=false
n8n_changed=false

## 7. Ready status

READY_FOR_CONTROLLED_BACKFILL
