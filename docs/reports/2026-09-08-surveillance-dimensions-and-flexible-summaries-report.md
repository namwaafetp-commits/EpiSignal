# Surveillance dimensions and flexible summaries report

## Outcome

Implemented the approved additive EpiSignal update locally on
`codex/next-iteration`. The implementation is committed as `bb7aaeb`.

- Disease groups are derived from the explicit mapping of all 30 seeded disease
  slugs. No disease-group database column was added; unmapped and missing values
  resolve to `unknown`.
- DeepSeek classification now emits nullable persisted `host_sector` values:
  `human`, `animal`, `both`, or `unknown`. Missing historical values remain
  `unknown`; event-level derivation uses the explicit both-sector precedence.
- Mistral summaries now accept a strict flexible `{title, bullets, takeaway}`
  payload with 3–5 bullets, while the previous structured summary contract and
  renderer remain readable for legacy rows.
- API, contracts, event pages, dashboard cards, filters, and search expose the
  additive fields. Flexible payloads are persisted in event and summary history
  so API/UI rendering is stable across future model runs.

## Scope preserved

No event matching logic, GDELT discovery, monitoring semantics, thresholds,
production model routing, cron, requeue, backfill, deployment, VPS, Coolify, or
production database operation was performed. The migration is local source only;
the expected new Alembic head is `20260908_0023`.

## Verification

The real repository gate passed after committing generated contracts:

```text
corepack pnpm verify
308 files already formatted
All matched files use Prettier code style!
All checks passed!
Success: no issues found in 147 source files
Test Files  14 passed (14)
Tests  117 passed (117)
1458 passed, 2 skipped, 2 warnings
Compiled successfully in 2.1min
Generating static pages using 8 workers (6/6)
```

The two skipped tests require `EPISIGNAL_TEST_DATABASE_URL`. The warnings are
the existing Starlette/httpx and AnyIO deprecations; Vite emitted its existing
configuration warnings during web tests.

Additional focused evidence included disease taxonomy/fallback, host-sector
precedence and persistence, production-shaped event reads and filters, flexible
summary validation/legacy fallback, UI rendering, migration shape, OpenAPI,
and contract generation.

