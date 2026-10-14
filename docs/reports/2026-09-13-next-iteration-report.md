# Next iteration production-quality fixes

## Root cause

MapLibre native GeoJSON clustering collapsed nearby events into aggregate
features. The old overlap dialog was only reachable after clicking a rendered
stack, so clustered events had no independent hover target.

Location reconciliation compared complete location identities. A country-only
answer and a town-plus-country answer therefore disagreed even when their
country identity was the same. Extraction metadata already preserves the
active `town` and `country` fields; no schema expansion or geocoding reorder was
needed.

Relevance classification had no contextual rule for consumer/travel rankings or
disease-free locality reporting, so those patterns could be treated as events.

## Map

- Native clustering and `events-clusters` / `events-cluster-count` layers removed.
- Stable public-ID-sorted fan-out offsets handle exact and near coordinate collisions.
- GeoJSON properties retain canonical latitude/longitude; API event objects are not mutated.
- Every displayed feature keeps independent hover tooltip, click/tap selection, and selected styling.
- Obsolete overlap-list UI and CSS removed.

## Location

- Country identity reconciles first.
- Cross-country disagreement returns unresolved; no majority vote.
- Same-country specificity coarsens to the shared admin1 or country when towns/admin2 values conflict.
- A compatible town remains when it is consistently supported.
- Unresolved peers do not veto a valid country.
- Reviewed DR Congo aliases resolve to `CD`; Bangladesh and Australia/Kangaroo Island cases retain country identity.

## Relevance

Added narrowly scoped classification guidance and prompt regressions for:

- consumer/travel food-poisoning rankings without an active event;
- disease-free locality stories without a current infectious event;
- contextual disease-free locality mentions that must not suppress a real outbreak elsewhere.

## Existing data

The prospective fix does not rewrite existing events. Added
`metadata:repair-stored`, which requires repeated explicit `--public-id` values,
defaults to dry-run/read-only mode, uses stored extraction evidence only, makes
no AI/retrieval/discovery calls, and applies only proposed metadata for those
IDs when explicitly passed `--apply`. It was not run against production.

## Verification

Focused backend and map tests passed. Full gate passed with
`VITEST_MAX_WORKERS=1 corepack pnpm verify`:

- 158 web tests passed;
- 1,543 Python tests passed, 2 skipped;
- 2 existing Python deprecation warnings;
- contracts generated with no diff;
- Next production build passed;
- Alembic head: `20260912_0025`.

Default parallel Vitest mode was also attempted, but unrelated existing tests
hit 5-second timeouts under shared-machine load; the one-worker run passed all
158 web tests.

## Production safety

VPS: not accessed. Coolify: not accessed. Production: not accessed. Pipeline:
not triggered. Broad backfill: not run. Deployment: not performed.
