# Handoff — Sub-Project E: Signal Radar

**Date:** 2026-08-28
**Branch:** `main`
**State:** `E` is **planned**. The design and the 15-task implementation plan are committed.
**Role:** Implementation worker.

---

## Outcome

Replace the evidence-proof homepage with a real signal-first radar. The same
validated recent-signal response must drive a MapLibre map and an accessible
ranked list. Every card must show its English title, the five ordered C2 brief
slots, separate uncertainty facts, honest location precision, and the original
publisher link. Add a separate read-only `/admin/pipeline` page for counts-only
pipeline history.

The approved design is
`docs/superpowers/specs/2026-08-28-signal-radar-design.md`. The executable plan
is `docs/superpowers/plans/2026-08-28-signal-radar.md`.

## Start here

1. Read `AGENTS.md`, `STATUS.md`, and `docs/agents/workflow.md`.
2. Read the approved design and implementation plan in full.
3. Load `superpowers:executing-plans`, then the project-local `lean-build`,
   `tdd`, and `migration` skills.
4. Before editing Next.js files, read the applicable local documentation under
   `apps/web/node_modules/next/dist/docs/` as required by `apps/web/AGENTS.md`.
5. Start Task 1. Set the `E` roadmap row to `building` in that task's commit and
   tick the matching `STATUS.md` checkbox in every task commit.

## Load-bearing decisions

- `/api/v1/signals` stays the raw-evidence seam. Add a dedicated
  `/api/v1/radar?hours=48&limit=50` read.
- The radar selects schema-v2, non-duplicate signals in `extracted`, `geocoded`,
  `matched`, or `published` state. It works when no event exists.
- Recency ranks first; attached-event `early_signal_score` breaks equal-time
  ties; UUID makes ties deterministic. Never blend it with `evidence_score`.
- A representative signal location prefers `primary`, then recorded precision,
  then stable location UUID. Unresolved locations stay list-only; country and
  province centroids are labelled as coarse.
- Zero event links means `none`; one means `attached`; several means
  `ambiguous` with no event selected.
- `packages/backend/src/episignal_backend/radar.py` owns both read queries.
- Use `maplibre-gl` directly in one small client component. Do not merge
  `feat/map-hero` or copy its generic map component.
- `/api/v1/admin/pipeline-runs` and `/admin/pipeline` expose counts, stage names,
  and exception type only. They have no controls.
- Old pipeline failure rows store stage strings. New rows must safely preserve
  `{stage, error}` while the reader remains backward compatible.

## Scope guard

Do not build event detail APIs/pages, search, export, review actions, scheduler
controls, auth, alerts, marker clustering, heatmaps, custom basemaps, dark mode,
or a new design system. Do not expose raw text, prompts, keys, exception
messages, or patient-level data.

## Completion

Task 15 loads `code-review`, then `verify-and-stop`, runs the real
`corepack pnpm verify` gate, captures live radar and browser proof, and writes
`docs/reports/2026-08-28-subproject-e-report.md`. Record the actual output and
verified baseline, commit the report, and hand back to the planner. The worker
does not mark `E` verified or begin another roadmap item.

## Incoming baseline

At `b26e794`, `corepack pnpm verify` passed with 789 Python tests, 10 web tests,
clean Ruff, mypy across 93 source files, generated-contract parity, and a
successful Next.js production build. The live database and PostGIS check passed.
