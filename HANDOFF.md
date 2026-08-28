# Handoff — Sub-Project E: Signal Radar

**Date:** 2026-08-28
**Branch:** `main`
**State:** `P0`–`P3`, `A`, `B`, `C`, `C2`, `D1`, `D2a`, and `L` are verified. `E` is **designed**. Its spec is committed; no implementation plan exists yet.
**Role:** Planner. Do not hand this file to an implementation worker as a build plan.

---

## Why this item is next

The pipeline now discovers, retrieves, deduplicates, classifies, extracts,
geocodes, clusters, matches, scores, and schedules real reporting. `C2` added the
stable display shape the product needed: an English title and five ordered brief
slots with source-language spans preserved as evidence.

The next missing piece is the product surface. `E` ends when a user can see an
early signal, understand its uncertainty, and open the original source. It is
the first item that turns the verified pipeline into something a person can use.

---

## Settled product decisions

Do not reopen these unless the operator explicitly changes them:

1. The homepage becomes the radar. There is no second competing homepage.
2. A large map shows the last day or two, with a ranked list beneath it.
3. Ranking uses recency and heat while keeping `early_signal_score` separate
   from `evidence_score`.
4. `E` renders the English title and five-slot brief written by `C2`; it does not
   summarize again in the API or browser.
5. Every visible claim keeps a path to the original source.
6. The radar must work from signals even when event coverage is sparse. Events
   are the layer above signals, not a reason to render an empty product.
7. `H` later refines the same homepage. `E` should establish the durable seams,
   not build all of `H`, `I`, `J`, or `K` early.

---

## Design questions still open

The design spec must settle these before an implementation plan exists:

1. The exact read model joining a signal, its English brief, resolved location,
   source standing, processing state, and any attached event scores.
2. The public API boundary: extend `/api/v1/signals` or introduce a dedicated
   radar endpoint without duplicating evidence-query logic.
3. The ranking formula and tie-breaks for recent signals without an event.
4. How uncertainty is worded from source standing, extraction confidence,
   location precision, and verification status without collapsing them into one
   confidence label.
5. Map behavior for place, district, province, country, and unresolved
   locations, including honest display of coarse precision.
6. Loading, unavailable, empty, and partial-data states on desktop and mobile.
7. Whether admin monitoring belongs in the first vertical slice or a second
   plan under the same roadmap item.
8. Whether any code from `feat/map-hero` is still worth salvaging. Inspect it;
   do not merge it wholesale or assume its dependencies still fit `main`.

---

## Start here

Read in this order:

1. `STATUS.md` — current position and settled `E` decisions.
2. `ROADMAP.md` — `E`'s completion condition and neighboring product items.
3. `docs/agents/workflow.md` — planner/worker ownership and completion gate.
4. `CONTEXT.md` — signal, event, observation, early signal score, evidence score,
   verification status, English title, brief, slot, and precision vocabulary.
5. `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md` — `E`'s
   architectural position.
6. `docs/superpowers/specs/2026-08-28-english-brief-design.md` — the display
   contract `E` consumes.
7. `docs/superpowers/specs/2026-08-28-story-clustering-design.md` — event scores,
   verification, observations, and conservative matching.
8. `docs/superpowers/specs/2026-08-27-geocoding-design.md` — coordinate precision
   and ambiguity rules.
9. `docs/superpowers/specs/2026-08-28-scheduler-design.md` — pipeline-run records
   available for monitoring.
10. `apps/api/src/episignal_api/routes/signals.py`,
    `apps/api/src/episignal_api/dependencies.py`, and
    `packages/backend/src/episignal_backend/evidence.py` — current read seam.
11. `apps/web/src/components/home-shell.tsx`, `apps/web/src/lib/api-signals.ts`,
    and `apps/web/src/app/globals.css` — current product surface.
12. `packages/backend/src/episignal_backend/models/signal.py`,
    `models/event.py`, `models/geography.py`, and `models/pipeline.py` — data the
    radar may read.
13. `docs/reports/2026-08-28-subproject-c2-report.md` — coherent live Indonesian
    signal proving the brief contract.
14. `docs/handoffs/2026-08-28-c2.md` — archived reasoning for the outgoing item.

---

## Required design invariants

1. **Evidence before claims.** A card links to the publisher and never presents
   model prose as official confirmation.
2. **Scores stay separate.** `early_signal_score` is surveillance interest;
   `evidence_score` is support. UI labels and API fields must preserve both.
3. **Precision stays visible.** A country centroid is not displayed as a town.
   Unresolved places remain visible as unresolved, never placed at null island.
4. **Observation history stays historical.** The surface may select a latest
   observation, but it must not overwrite or imply that older values vanished.
5. **No patient-level data.** Do not expose names, contact details, or full raw
   text on the public radar.
6. **No synthetic fallback data.** Empty or unavailable states say so.
7. **Responsive from the first implementation commit.** Map and list must remain
   usable on small screens; desktop-only acceptance is insufficient.
8. **Accessibility is structural.** Map information must also exist in the list,
   keyboard focus must be visible, and color cannot carry uncertainty alone.

---

## Scope boundaries

`E` may design and implement the radar read model, API, homepage map/list, and
the minimum monitoring surface required by its roadmap row.

Do not absorb these later items:

- `D2b`: embedding similarity or LLM matching escalation;
- `G`: the full public event API;
- `H`: the final homepage event feed and refinement pass;
- `I`: event detail pages and timelines;
- `J`: search;
- `K`: export;
- `M`: the human review queue;
- `N`: final SEO, performance, and accessibility acceptance work.

---

## Planner next action

Ask the operator to review
`docs/superpowers/specs/2026-08-28-signal-radar-design.md`. After written-spec
approval, write the implementation plan and copy its tasks into `STATUS.md`.
Until the plan exists, there is no worker implementation task.

---

## Verified incoming baseline

The worker's `C2` gate ran at `b26e794` and is recorded untruncated in
`docs/reports/2026-08-28-subproject-c2-report.md`:

- `corepack pnpm verify` — exit code 0;
- 789 Python tests, 1 warning;
- 10 web tests across 3 files;
- Ruff, Prettier, ESLint, mypy across 93 source files, contracts, and Next.js
  production build clean.

The planner independently re-ran the same gate at `888369c`, then reviewed the
documentation-only closure through `caefb6d`. `git diff --check 11d2833...HEAD`
and `git status --short` were clean before C2 was marked verified.
