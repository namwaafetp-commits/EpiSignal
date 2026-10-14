# Final map architecture cleanup report

Date: 2026-09-13
Baseline: `b042658`
Branch: `codex/next-iteration`

## Map architecture

- Source count: exactly one GeoJSON source, `events`.
- Circle layer count: exactly one circle layer, `events-circles`.
- Per-event layers: none.
- Screen-space separation: 16 px minimum, using MapLibre project/unproject;
  display geometry is temporary and deterministic by `public_id`.
- Viewport recalculation: recompute source data on data changes, `moveend`, and
  `zoomend`; coalesce continuous `resize` events with
  `requestAnimationFrame`; style reload rebuilds the same source/layer pair.
- Stale layer behavior: no event-specific layers exist, so filtered event sets
  cannot accumulate stale style layers.
- Canonical API coordinates changed: no. API objects and canonical coordinate
  properties remain unchanged; selection and flyTo use canonical coordinates.

## Interaction

- Hover: one delegated handler on `events-circles`, reading headline/location
  from feature properties.
- Click/tap: one delegated handler on `events-circles`, selecting feature `id`.
- Selected styling: shared-layer MapLibre expressions keyed by `public_id`.
- FlyTo coordinate: canonical event `[longitude, latitude]`.

## Logo

Dockerfile public copy preserved unchanged:

```dockerfile
COPY --from=builder --chown=episignal:episignal /app/apps/web/public ./apps/web/public
```

No Docker runtime test was run; Docker is unavailable locally and runtime
testing was removed from scope by user instruction.

## Tests

- Focused map suite: 29 passed.
- Web suite: 166 passed.
- Python suite: 1,543 passed, 2 skipped, 2 warnings.
- Full verify: passed with format, lint, typecheck, contracts, tests, and build.
- Alembic head: `20260912_0025`.

## Safety

No backend, location reconciliation, relevance, repair, migration, production,
VPS, Coolify, pipeline, metadata repair, or deployment work was performed.
