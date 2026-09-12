# Event-summary model-roster migration report

Date: 2026-09-12  
Branch: `codex/next-iteration`  
Implementation commit: `f816cf1`

## ROOT CAUSE

Production `EVENT_SUMMARY` roster before the fix was the old active Mistral
route, `mistralai/mistral-small-3.2-24b-instruct`, while the production
DeepSeek row used by classification was a separate active roster fact. The
reported run therefore proved that the OpenRouter provider key and DeepSeek
classification path worked, but it did not prove that the summary route's
purpose-specific row existed.

The DeepSeek summary route was changed in Python in `982157f`; Python route
constants do not mutate `ai_models`. The reviewed JSON seed is also applied by
the separate `db:seed` command, and API startup does not apply migrations or
seeds. A normal migration-only deployment consequently left the existing
Mistral `event_summary` row in place and did not create/update the DeepSeek
summary roster fact. `SqlAlchemyAiRepository.models()` correctly exposed only
active database rows, so `configure_summary()` could not resolve the new exact
DeepSeek/OpenRouter summary route.

Classification still worked because its DeepSeek/OpenRouter row was already
active and matched the classification route. The final roster keeps the one
unique DeepSeek model row purpose-scoped as `event_summary`; the registry
explicitly treats that exact same DeepSeek route as shared by classification,
preserving both live passes without weakening unrelated purpose scoping.

## FIX

- Seed/migration changed: added Alembic revision `20260912_0025`, chained from
  `20260911_0024`. It upserts the canonical DeepSeek row with tier 1,
  `provider=openrouter`, `purpose=event_summary`, prices `0.03`/`0.10`, and
  `active=true`. The canonical seed now carries the same row and an explicit
  inactive retired Mistral row.
- Old Mistral row behavior: `mistralai/mistral-small-3.2-24b-instruct` is
  retained for audit/request-ledger identity and deterministically set
  `active=false`; it is never deleted.
- New DeepSeek EVENT_SUMMARY row: existing DeepSeek rows are corrected in
  place; absent rows are inserted. `SqlAlchemyAiRepository.models()` therefore
  exposes one active DeepSeek summary spec after migration.
- Idempotency: the migration uses `ON CONFLICT (model_id) DO UPDATE`; rerunning
  the reviewed seed converges to the same active/inactive state. No event,
  event-summary, or AI-request history is rewritten.

## TESTS

- fresh DB: dedicated PostgreSQL integration test resets an isolated test DB,
  upgrades from base to head, runs normal bootstrap, and verifies the active
  roster. Local run: skipped because `EPISIGNAL_TEST_DATABASE_URL` was not
  configured.
- upgrade existing DB: dedicated integration test creates the pre-change
  DeepSeek classification + active Mistral summary roster, upgrades to head,
  verifies DeepSeek summary resolution and Mistral deactivation, and checks
  summary history remains untouched. Local run: skipped for the same reason.
- configure_summary: verifies OpenRouter and
  `deepseek/deepseek-v4-flash-0731` from repository-backed active specs.
- three-model pipeline: seeded roster regression verifies DeepSeek
  classification, Gemini extraction, and DeepSeek summarization.

## VERIFY

- Python: `1533 passed, 2 skipped, 2 warnings` via `corepack pnpm verify`
- Web: `125 passed`
- format: 319 files formatted; Prettier clean
- lint: Ruff and ESLint passed
- typecheck: mypy success for 149 Python source files; web TypeScript passed
- contracts: OpenAPI regenerated with no contract diff
- build: Next.js production build passed
- Alembic: one linear head, offline migration rendering and roster revision
  tests passed; head `20260912_0025`

## GIT

- Previous HEAD: `a773799`
- New HEAD: `f816cf1` implementation commit; the final report/ledger commit is
  added after this report
- Remote HEAD: `a773799` at implementation verification time
- Working tree: clean after the implementation commit

## PRODUCTION

- Deployed: NO
- Production DB changed: NO
- VPS accessed: NO
- Coolify accessed: NO
