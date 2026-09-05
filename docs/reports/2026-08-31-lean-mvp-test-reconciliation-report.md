# EpiSignal Lean MVP Test Reconciliation Report

## 1. Starting State
- branch: `codex/next-iteration`
- starting SHA: `e073ed519ac44603d8fcfa3aa82d4838c80eea0a`
- backend passed: 1185
- backend failed: 37
- Ruff format failures: 3

## 2. Failure Groups

| Group | Failures before | Root cause | Resolution |
|---|---:|---|---|
| stage/runtime expectations | 5 | Tests expected retired stages, the old threshold, and legacy runner behavior. | Updated schedule, discovery, and configuration expectations to the Lean MVP runtime. |
| matching/geospatial | 13 | Tests expected embedding similarity, an LLM match judge, old ambiguity behavior, and `ST_DWithin`. | Updated tests to deterministic country-level candidate selection and conservative event creation. |
| review/status | 8 | Tests expected runtime human-review routing and legacy retrieval statuses. | Updated tests to preserve signals/events without opening runtime review cases. |
| repository/storage fakes | 10 | Fakes implemented retired repository methods and stale extraction/classification predicates. | Reconciled fakes and queries with current repository protocols and storage fields. |
| OpenAPI | 1 | The public dashboard route was omitted from the expected route set. | Added `/api/v1/events/dashboard` to the expectation. |
| other | 0 | None. | None. |

## 3. Production Code Changes

- file: `packages/backend/src/episignal_backend/events/repository.py`
  - reason: Ruff formatting only.
  - real bug or test-support change: Neither; no behavior change.
- file: `packages/backend/src/episignal_backend/requeue.py`
  - reason: Ruff formatting only.
  - real bug or test-support change: Neither; no behavior change.
- file: `packages/backend/src/episignal_backend/schedule/stages.py`
  - reason: Ruff formatting only.
  - real bug or test-support change: Neither; no behavior change.

## 4. Test Changes

Updated the stale expectations and fakes in the AI classification/extraction and repository tests, discovery/retrieval tests, event assembly/judge/matching/repository tests, schedule tests, configuration test, GDELT connector test, and API OpenAPI test. Formatted the existing branch-added `apps/web/src/components/event-map.test.tsx` so the repository Prettier gate passes.

## 5. OpenAPI
- dashboard route intentionally public: YES
- resolution: The web dashboard and API client call `/api/v1/events/dashboard`; the OpenAPI test now includes the route.

## 6. Lean MVP Guard Check

Confirm these remain absent from production runtime:

- ECDC: absent from `DAILY_CHAIN`
- PREGROUP: absent from `DAILY_CHAIN`
- runtime geocoding: absent from matching runtime
- embeddings: absent from matching runtime
- LLM match judge: absent from assembly runtime
- human review: absent from assembly/discovery runtime
- NEEDS_REVIEW: absent from the active runtime routing
- old 0.75 threshold: replaced by the Lean MVP configuration value `0.60`
- ST_DWithin event matching: absent

## 7. Final Verification
- backend tests: PASS — `1222 passed, 2 warnings`
- frontend tests: PASS — `14` files, `105 passed`
- Ruff lint: PASS
- Ruff format: PASS — `269 files already formatted`
- mypy: PASS — `131 source files`
- TypeScript typecheck: PASS
- Next.js production build: PASS

The exact command `corepack pnpm verify` passed at commit `ad26140` with the outputs above.

## 8. Remaining Failures
- count: 0
- details: None.

Target: 0

## 9. Database / Pipeline
- Supabase modified: NO
- migrations run: NO
- pipeline run: NO
- deployment performed: NO

## 10. Commit
- branch: `codex/next-iteration`
- SHA: `ad26140` (verification commit; the final amended commit retains the same focused change)

## 11. Readiness

READY_FOR_VPS_DOCKER_VALIDATION

Reason: The Lean MVP test baseline is clean and all repository verification gates pass. VPS Docker validation remains a separate next step.
