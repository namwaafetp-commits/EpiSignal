# Final pre-deploy fixes report

Date: 2026-09-13
Baseline: `b307a9e`
Branch: `codex/next-iteration`

## Map

- Old behavior: fixed geographic-degree collision and fan-out offsets.
- New strategy: MapLibre `project`/`unproject` screen-space collision detection
  and deterministic fan-out ordered by `public_id`.
- Minimum visual separation: 16 px center-to-center.
- Zoom behavior: positions recalculate after data updates, `moveend`, and
  `zoomend`; canonical positions return when projected points no longer collide.
- Canonical coordinates changed: no. Display offsets are not persisted.
- Hover/click: one unclustered feature remains present per mapped event; each
  feature retains its own `public_id`.
- Selection: selected state remains keyed by `public_id`; navigation uses
  canonical coordinates.

## Logo

- Root cause: runtime image omitted `apps/web/public`.
- Dockerfile change: runtime now copies `/app/apps/web/public` while retaining
  standalone and static copies.
- Container asset test: removed from scope per user instruction. Docker is not
  available on this host, so no HTTP claim is made.

## Backend

Location reconciliation changed: no.

Relevance changed: no.

Repair tool changed: no.

## Tests

- Focused map suite: 26 passed.
- Web typecheck: passed.
- Web lint: passed.
- Web production build: passed.
- Docker asset test: not run; removed per user instruction.

## Verify

`VITEST_MAX_WORKERS=1 corepack pnpm verify`: passed.

- Format: passed; 321 files already formatted.
- Lint: passed; Ruff reported `All checks passed!`.
- Typecheck: passed; mypy reported `Success: no issues found in 150 source files`.
- Web: 163 tests passed.
- Python: 1,543 passed, 2 skipped, 2 warnings.
- Contracts: generated and unchanged.
- Web build: passed.

Alembic head remains `20260912_0025`.

## Git and production safety

Previous HEAD: `b307a9e`.

No production systems, VPS, Coolify, production pipeline, or metadata repair
were accessed or triggered. No deployment was performed.
