# EpiSignal Production Validation Report

## 1. Backend Test Comparison

Exact command: `uv run pytest`, with the same copied `apps/api/.env` configuration for both checkouts.

### main
- passed: 1202
- failed: 1

### containerization branch
- passed: 1185
- failed: 37

### Classification
- pre-existing: all 37 containerization-branch failures. The same 37 failures were present at parent commit `13f54cc` before containerization commit `74cf0cc`; the main checkout has the shared OpenAPI failure.
- new regressions: none
- environment-specific: none under equivalent configuration

### New regressions
- NONE

The 37 failing names are: `apps/api/tests/test_openapi.py::test_openapi_exposes_public_routes`; `packages/backend/tests/test_ai_classify.py::test_rejection_at_every_tier_sends_the_whole_batch_for_review`; `packages/backend/tests/test_ai_extract.py::test_a_vocabulary_miss_asks_the_smartest_rung_and_stores_its_answer`; `packages/backend/tests/test_ai_extract.py::test_an_ungrounded_answer_at_every_tier_sends_one_signal_for_review`; `packages/backend/tests/test_ai_extract.py::test_one_failing_signal_does_not_stop_the_rest_of_the_queue`; `packages/backend/tests/test_ai_extract.py::test_a_rejected_first_extraction_still_goes_to_review`; `packages/backend/tests/test_ai_protocol.py::test_a_repository_is_recognised_by_the_whole_storage_boundary`; `packages/backend/tests/test_ai_repository.py::test_awaiting_triage_returns_source_metadata_and_uses_the_blocking_filters`; `packages/backend/tests/test_ai_repository.py::test_normalized_and_legacy_classified_signals_are_both_extractable`; `packages/backend/tests/test_ai_repository.py::test_a_signal_a_model_called_irrelevant_is_not_extractable`; `packages/backend/tests/test_ai_repository.py::test_a_deferred_member_of_an_open_group_is_not_extracted_alone`; `packages/backend/tests/test_config.py::test_event_matching_defaults_are_set`; `packages/backend/tests/test_discover_runner.py::test_retry_runs_before_discovery`; `packages/backend/tests/test_discovery_repository.py::test_initial_contentless_discovery_opens_retrieval_failed_case`; `packages/backend/tests/test_discovery_repository.py::test_record_failed_attempt_opens_retrieval_failed_when_max_attempts_reached`; `packages/backend/tests/test_discovery_repository.py::test_promotion_closes_open_retrieval_case_automatically`; `packages/backend/tests/test_discovery_repository.py::test_the_retry_pass_only_sees_needs_review_stubs`; `packages/backend/tests/test_event_assemble.py::test_unclusterable_signal_routes_to_needs_review`; `packages/backend/tests/test_event_assemble.py::test_similarity_is_wired_lazily_and_every_candidate_decision_is_logged`; `packages/backend/tests/test_event_assemble.py::test_refusal_routes_signals_to_needs_review`; `packages/backend/tests/test_event_judge.py::test_an_ambiguous_match_attaches_when_the_judge_says_same_event`; `packages/backend/tests/test_event_judge.py::test_an_ambiguous_match_creates_a_new_event_when_the_judge_disagrees`; `packages/backend/tests/test_event_judge.py::test_an_ambiguous_match_without_a_judge_prefers_a_new_event`; `packages/backend/tests/test_event_judge.py::test_an_unavailable_judge_prefers_a_new_event`; `packages/backend/tests/test_event_match.py::test_same_disease_same_country_without_admin1_is_ambiguous_not_attached`; `packages/backend/tests/test_event_repository.py::test_signals_to_match_queries_geocoded_signals_and_maps_locations`; `packages/backend/tests/test_event_repository.py::test_candidate_events_spatial_narrowing_rule`; `packages/backend/tests/test_event_repository.py::test_candidates_are_bounded_by_lookback_and_limit`; `packages/backend/tests/test_event_repository.py::test_a_different_disease_is_never_a_candidate`; `packages/backend/tests/test_event_repository.py::test_a_cluster_without_geography_still_gets_candidates`; `packages/backend/tests/test_event_repository.py::test_candidate_events_map_the_primary_signal_embedding`; `packages/backend/tests/test_event_repository.py::test_open_review_updates_signal_and_persists_review_case`; `packages/backend/tests/test_gdelt_connector.py::test_stub_for_a_failed_retrieval_is_built_by_the_connector`; `packages/backend/tests/test_schedule_chains.py::test_triage_runs_after_dedupe_and_before_grouping`; `packages/backend/tests/test_schedule_chains.py::test_grouping_precedes_extraction`; `packages/backend/tests/test_schedule_chains.py::test_every_stage_appears_exactly_once`; `packages/backend/tests/test_schedule_stages.py::test_the_mapping_covers_exactly_the_stage_names`.

## 2. Formatting
- formatter: Ruff format (`uv run ruff format --check .`)
- main status: PASS; 267 files already formatted
- branch status: FAIL; 3 files would be reformatted
- branch-introduced problems: none from containerization. The failures are present at parent `13f54cc`; files are `packages/backend/src/episignal_backend/events/repository.py`, `packages/backend/src/episignal_backend/requeue.py`, and `packages/backend/src/episignal_backend/schedule/stages.py`.

Lint is separate from formatting: Ruff lint, ESLint, and Python lint all pass.

## 3. API Dockerfile
- startup command validated: PASS; `python -m episignal_api.run` reads the configured bind host and port
- workspace dependency closure: PASS; `uv sync --frozen --package episignal-api --no-dev --dry-run` resolves the API workspace package and backend dependency
- pipeline available: PASS; `episignal_backend.pipeline_runner` imports from the API package environment
- health endpoint: PASS; `/health/live`
- secrets excluded: PASS; `.dockerignore` excludes environment files
- issues found: Docker image build unavailable because Docker is not installed locally

## 4. Web Dockerfile
- standalone output validated: PASS; `apps/web/.next/standalone/apps/web/server.js` and `.next/static` exist
- runtime server path: PASS; `node apps/web/server.js`
- static assets: PASS; copied to `apps/web/.next/static`
- NEXT_PUBLIC build-time handling: PASS; supplied through Docker `ARG`/build `ENV`
- secrets excluded: PASS
- issues found: no `apps/web/public` directory exists; no copy is required

## 5. Compose
- services: `episignal-api`, `episignal-web` only
- external network: `episignal_proxy`, external, named explicitly
- host ports exposed: none
- Traefik entrypoint: `websecure`
- certificate resolver: `mytlschallenge`
- traefik.docker.network: `episignal_proxy` on both services
- issues found: Docker Compose runtime validation unavailable because Docker is not installed locally; YAML and static contract validation pass

## 6. Environment Contract
- API bind host variable: `EPISIGNAL_API_BIND_HOST`, default `0.0.0.0`; legacy `EPISIGNAL_API_HOST` remains accepted by Settings only for compatibility
- public API hostname variable: `EPISIGNAL_API_PUBLIC_HOST`, required directly by Compose routing; `EPISIGNAL_API_HOST` is not used for routing
- collision found: yes in the initial containerization contract; fixed by separating public routing and bind variables and wiring the bind value into API startup
- CORS: `EPISIGNAL_CORS_ORIGINS` is the HTTPS web origin
- frontend API URL: `NEXT_PUBLIC_EPISIGNAL_API_URL` is the HTTPS API URL baked into the web build
- database and OpenRouter values remain host-provided secrets/placeholders; no production values are committed

## 7. Pipeline
- executable available in API image definition: PASS; the API image installs the `episignal-api` package and its workspace `episignal-backend` dependency, which contains `episignal_backend.pipeline_runner`
- pipeline executed: NO

## 8. Changes Made
- files: `.env.production.example`, `apps/api/Dockerfile`, `docker-compose.prod.yml`, `packages/backend/src/episignal_backend/config.py`, `packages/backend/tests/test_config.py`, and this report
- reason: separate public/bind host semantics, wire the bind setting into production startup, preserve legacy configuration callers, and record the validation evidence

## 9. Verification Status

- backend regression check: PASS for regression classification; current branch has 37 pre-existing failures and 1185 passing tests, with no containerization-introduced failure
- frontend tests: PASS; 105 tests in 14 files
- lint: PASS; web ESLint and Python Ruff lint
- formatting: FAIL; 3 pre-existing Ruff format failures listed above
- typecheck: PASS; web TypeScript typecheck and Python mypy passed in the containerization verification
- Next.js build: PASS; standalone production build completed in the containerization verification
- Docker build: NOT RUN — Docker unavailable
- Docker Compose runtime validation: NOT RUN — Docker unavailable
- `corepack pnpm verify`: FAIL at the formatting step with the same 3 pre-existing Ruff format failures; it did not reach later stages

## 10. Deployment Readiness

READY_FOR_VPS_DOCKER_VALIDATION

Reason: no regression was introduced by containerization, static Dockerfile/Compose/package checks pass, and the host-variable collision is fixed. The VPS Docker validation step is still required because Docker is unavailable locally. Do not deploy from this workstation.

## 11. Commit
- branch: `codex/next-iteration`
- SHA: `36842959e2bed50728f2fc09cdfed80445dcc112` (validated implementation; report commit follows)
