# Signal Radar and Pipeline Monitor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Also load the project-local `lean-build`, `tdd`, and `migration` skills before Task 1. Before completion, load `code-review` and then `verify-and-stop`. Tick each task in `STATUS.md` in the same commit as the work.

**Item:** `E`

**Goal:** Replace the evidence-proof homepage with a real 48-hour signal radar: one signal-first API response drives an accessible MapLibre map and ranked five-slot brief list, while a separate read-only admin page exposes recent pipeline health without secrets or controls.

**Architecture:** `packages/backend/src/episignal_backend/radar.py` is the read boundary. It assembles frozen radar and pipeline-run read models from existing schema-v2 extractions, source standing, representative signal locations, optional event context, and counts-only pipeline records. FastAPI exposes `/api/v1/radar` and `/api/v1/admin/pipeline-runs` through injectable dependencies. Next.js validates both responses at runtime. The homepage passes one validated item set to both a small direct MapLibre client component and the accessible card list; `/admin/pipeline` renders counts only.

**Tech stack:** Python 3.12, SQLAlchemy 2, FastAPI/Pydantic v2, pytest, Next.js 16.3.2, React 19, TypeScript, Vitest/Testing Library, MapLibre GL, generated OpenAPI TypeScript contracts.

**Design:** [docs/superpowers/specs/2026-08-28-signal-radar-design.md](../specs/2026-08-28-signal-radar-design.md)

**Incoming verified baseline:** `b26e794`; 789 Python tests and 10 web tests passed. Planner documentation through `9294ae4` is clean.

---

## Scope check

The public radar and admin monitor are independent presentation slices, but
both consume the same new read module and together define roadmap item `E`'s
completion gate. This plan keeps them in one ledger while landing the radar
first as working, testable software at Task 12; Tasks 13–14 then add the monitor
without changing the public slice.

## Rules and stop conditions

- Work in the numbered order. Task 11 is the first browser-visible MVP, so do not start the admin page early.
- Every behavior change is red → green → refactor. Run the named failing test before implementation and record the expected failure in the commit notes when it is surprising.
- At Task 1, set `E` from `planned` to `building` in `ROADMAP.md`. Thereafter the worker changes only task ticks and the verified baseline in `STATUS.md`; it does not redesign the roadmap, spec, or plan.
- Before touching `apps/web`, read the relevant files under `apps/web/node_modules/next/dist/docs/` as required by `apps/web/AGENTS.md`. At minimum read the App Router server/client component, data fetching, CSS, and testing guidance applicable to the files in this plan.
- Tests through Task 14 open no socket and use no live database. Task 15 is the only live verification task.
- Never place raw article text, model prompts, keys, exception messages, or patient-level fields in either new response.
- Do not merge `feat/map-hero`, copy its generic map abstraction, or add its UI libraries. Reuse only the proven Carto Positron style URL and the precision vocabulary.
- Do not add clustering markers, heatmaps, search, event pages, export, review actions, scheduler controls, auth, dark mode, or synthetic fallback data.
- If the current schema cannot support one of the agreed response fields, stop and return to the planner. Do not silently invent a replacement.

## Target file structure

**Create:**

- `packages/backend/src/episignal_backend/radar.py`
- `packages/backend/tests/test_radar.py`
- `apps/api/src/episignal_api/routes/radar.py`
- `apps/api/src/episignal_api/routes/admin_pipeline.py`
- `apps/api/tests/test_radar.py`
- `apps/api/tests/test_admin_pipeline.py`
- `apps/web/src/lib/api-radar.ts`
- `apps/web/src/lib/api-radar.test.ts`
- `apps/web/src/lib/api-pipeline.ts`
- `apps/web/src/lib/api-pipeline.test.ts`
- `apps/web/src/components/signal-map.tsx`
- `apps/web/src/components/signal-map.test.tsx`
- `apps/web/src/app/admin/pipeline/page.tsx`
- `apps/web/src/components/pipeline-monitor.tsx`
- `apps/web/src/components/pipeline-monitor.test.tsx`
- `docs/reports/2026-08-28-subproject-e-report.md`

**Modify:**

- `packages/backend/src/episignal_backend/schedule/protocol.py`
- `packages/backend/src/episignal_backend/schedule/repository.py`
- `packages/backend/src/episignal_backend/pipeline_runner.py`
- their focused scheduler tests
- `apps/api/src/episignal_api/dependencies.py`
- `apps/api/src/episignal_api/factory.py`
- `apps/api/tests/test_openapi.py`
- `packages/contracts/openapi.json`
- `packages/contracts/src/index.d.ts`
- `apps/web/package.json` and `pnpm-lock.yaml`
- `apps/web/src/app/page.tsx`
- `apps/web/src/app/loading.tsx`
- `apps/web/src/components/home-shell.tsx`
- `apps/web/src/components/home-shell.test.tsx`
- `apps/web/src/app/globals.css`
- `ROADMAP.md` once at Task 1
- `STATUS.md` as tasks land and at the gate

---

## Canonical interfaces

Use these names and shapes throughout the tasks; do not create parallel DTOs:

```python
# packages/backend/src/episignal_backend/radar.py
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from episignal_backend.ai.schema import BriefPoint
from episignal_backend.db.types import (
    CredibilityTier,
    LocationRole,
    PipelineChain,
    PipelineRunStatus,
    PipelineTrigger,
    Precision,
    ProcessingStatus,
    SignalType,
    VerificationStatus,
)
from episignal_backend.schedule.documents import StageName


class EventContextStatus(StrEnum):
    NONE = "none"
    ATTACHED = "attached"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class RadarSource:
    name: str
    url: str
    is_official: bool
    credibility_tier: CredibilityTier


@dataclass(frozen=True)
class RadarLocation:
    role: LocationRole
    precision: Precision
    label: str
    country_code: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class RadarEventContext:
    public_id: str
    verification_status: VerificationStatus
    early_signal_score: float | None
    evidence_score: float | None


@dataclass(frozen=True)
class RadarItem:
    id: UUID
    title_english: str
    brief: tuple[BriefPoint, ...]
    signal_type: SignalType
    processing_status: ProcessingStatus
    published_at: datetime | None
    first_seen_at: datetime
    source: RadarSource
    extraction_confidence: float
    location: RadarLocation | None
    event_context_status: EventContextStatus
    event: RadarEventContext | None


@dataclass(frozen=True)
class RadarPage:
    items: tuple[RadarItem, ...]
    window_start: datetime
    window_end: datetime
    hours: int
    limit: int


@dataclass(frozen=True)
class PipelineFailure:
    stage: StageName
    error: str | None


@dataclass(frozen=True)
class PipelineRunItem:
    id: UUID
    chain: PipelineChain
    trigger: PipelineTrigger
    status: PipelineRunStatus
    started_at: datetime
    finished_at: datetime | None
    window_start: datetime | None
    window_end: datetime | None
    stage_counts: dict[str, dict[str, int]]
    backlog: dict[str, int]
    failures: tuple[PipelineFailure, ...]
    is_stale: bool


@dataclass(frozen=True)
class PipelineRunPage:
    items: tuple[PipelineRunItem, ...]
    limit: int
```

The public Python call signatures are
`choose_representative_location(locations: Sequence[SignalLocation]) -> RadarLocation | None`,
`query_radar(session: Session, *, now: datetime, hours: int = 48, limit: int = 50) -> RadarPage`,
and `query_pipeline_runs(session: Session, *, now: datetime,
stale_after_minutes: int, limit: int = 20) -> PipelineRunPage`.

```typescript
// apps/web/src/lib/api-radar.ts
import type { components } from "@episignal/contracts";

export type RadarResponse = components["schemas"]["RadarResponse"];
export type RadarItem = components["schemas"]["RadarItemResponse"];
export type RadarState =
  | { status: "loading"; data: null }
  | { status: "ready"; data: RadarResponse }
  | { status: "unavailable"; data: null };

export async function getRadar(hours = 48, limit = 50): Promise<RadarState>;

// apps/web/src/components/signal-map.tsx
export type SignalMapProps = {
  items: RadarItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
};

// apps/web/src/lib/api-pipeline.ts
export type PipelineRunResponse =
  components["schemas"]["PipelineRunListResponse"];
export type PipelineRunState =
  | { status: "loading"; data: null }
  | { status: "ready"; data: PipelineRunResponse }
  | { status: "unavailable"; data: null };

export async function getPipelineRuns(limit = 20): Promise<PipelineRunState>;
```

The TypeScript declarations are signature references. The function bodies are
implemented in Tasks 8 and 13; do not commit overload declarations without
bodies.

---

## Task 1: Preserve exception types in pipeline history

This is a compatibility-safe JSON transition, not a database migration. Existing `failed_stages: ["extract"]` rows must keep reading; new rows become `[{"stage": "extract", "error": "TimeoutError"}]`.

**Files:** modify `schedule/protocol.py`, `schedule/repository.py`, `pipeline_runner.py`, `packages/backend/tests/test_schedule_protocol.py`, `test_schedule_repository.py`, and `test_pipeline_runner.py`; update `ROADMAP.md` and tick Task 1 in `STATUS.md`.

- [ ] Add a failing repository test that calls `finish_run` with
      `failed_stages=[StageOutcome(stage=StageName.EXTRACT, ok=False, error="TimeoutError")]`
      and asserts the stored JSON contains only `stage` and `error`, never an
      exception message.
- [ ] Add a failing runner test proving the `ChainOutcome.outcomes` failure objects, not only `ChainOutcome.failed_stages`, cross the repository seam.
- [ ] Change the protocol and repository parameter to a sequence of failed `StageOutcome` values. Serialize exactly `{"stage": str(outcome.stage), "error": outcome.error}`. Assert the sequence contains only failed outcomes and never serialize `counts`.
- [ ] In `pipeline_runner.py`, pass `item for item in outcome.outcomes if not item.ok`.
- [ ] Run `uv run pytest packages/backend/tests/test_schedule_protocol.py packages/backend/tests/test_schedule_repository.py packages/backend/tests/test_pipeline_runner.py -v`; expect green.
- [ ] Set the `E` roadmap row to `building`, tick Task 1, and commit: `feat: preserve safe pipeline failure types`.

## Task 2: Define the radar read contracts and representative location rule

**Files:** create `radar.py` and `test_radar.py`.

- [ ] Write failing tests for frozen `RadarSource`, `RadarLocation`, `RadarEventContext`, `RadarItem`, `RadarPage`, `PipelineFailure`, `PipelineRunItem`, and `PipelineRunPage` dataclasses. The fields must exactly match the approved design; no model or ORM object crosses the seam.
- [ ] Write table-driven tests for `choose_representative_location`: primary role wins; otherwise use all roles; precision order is `place`, `admin2`, `admin1`, `country`, `unresolved`; equal precision uses ascending location UUID; population is never read; label fallback is `resolved_name`, `place_name`, `admin2`, `admin1`, `country_name`; unresolved coordinates are returned as null.
- [ ] Implement an `EventContextStatus(StrEnum)` with only `none`, `attached`, and `ambiguous`, a private precision-rank map, and the pure chooser. Ensure both coordinates must be present to be plottable; never coerce missing coordinates to zero.
- [ ] Run `uv run pytest packages/backend/tests/test_radar.py -v -k "contract or representative or location"`; expect green.
- [ ] Tick Task 2 and commit: `feat: define the signal radar read model`.

## Task 3: Query and assemble recent radar signals

**Files:** modify `radar.py` and `test_radar.py`.

- [ ] Build fake-session tests around public `query_radar(session, *, now, hours=48, limit=50)`. Assert:
  - the lower bound is `now - timedelta(hours=hours)` and upper bound is `now`;
  - effective time is `published_at` or `first_seen_at`;
  - only `extracted`, `geocoded`, `matched`, and `published` statuses are eligible;
  - duplicates and non-v2 rows are excluded by the statement;
  - ordering is effective time descending, the single attached event's `early_signal_score` descending with nulls last, then signal UUID descending; zero-link and multi-link signals have null heat for ranking;
  - the limit is bounded by the caller and applied to the signal selection, not multiplied join rows.
- [ ] Add assembly fixtures for: one valid unmatched signal, one attached event, multiple linked events, several locations, and a malformed stored extraction. Assert the malformed row is omitted rather than crashing the endpoint; `none` and `ambiguous` return `event=None`; `attached` preserves `early_signal_score` and `evidence_score` separately.
- [ ] Implement a three-read query: select eligible `Signal` + `Source` rows using a correlated event-heat subquery with `HAVING count(EventSignal.event_id) = 1`, so ambiguous links contribute null heat; then fetch all `SignalLocation` rows and all `EventSignal` + `Event` rows for the selected ids. Parse `Signal.ai_extraction` only with `StoredExtractionPayload.model_validate` and require non-null `title_english` plus exactly `BRIEF_SLOT_COUNT` points.
- [ ] Construct the source URL from `Signal.url`, not `Source.base_url`. Return `source.name`, `is_official`, and `credibility_tier`; do not select `raw_text`.
- [ ] Run `uv run pytest packages/backend/tests/test_radar.py -v -k "query_radar or ranking or event or extraction"`; expect green.
- [ ] Tick Task 3 and commit: `feat: query recent signals for the radar`.

## Task 4: Query counts-only pipeline history

**Files:** modify `radar.py` and `test_radar.py`.

- [ ] Add failing tests for `query_pipeline_runs(session, *, now, stale_after_minutes, limit=20)`: newest `started_at` first; limit applied; `stage_counts` and `backlog` are normalized to `dict[str, dict[str, int]]` and `dict[str, int]` respectively; malformed count values are rejected from that run rather than stringified; no unknown database fields leak.
- [ ] Prove compatibility for legacy failure strings (`"extract"` → stage with `error=None`) and new objects (`{"stage":"extract","error":"TimeoutError"}`). Ignore malformed failure entries. Never expose an error message.
- [ ] Define `is_stale` as `status == running and finished_at is None and now - started_at > 2 * stale_after_minutes`. The API dependency will pass `Settings.gdelt_poll_interval_minutes`, which is the configured external schedule interval documented for the daily chain.
- [ ] Implement the single ordered `PipelineRun` read and pure normalization helpers.
- [ ] Run `uv run pytest packages/backend/tests/test_radar.py -v -k "pipeline"`; expect green.
- [ ] Tick Task 4 and commit: `feat: read safe pipeline monitoring history`.

## Task 5: Expose `GET /api/v1/radar`

**Files:** create `routes/radar.py` and `apps/api/tests/test_radar.py`; modify `dependencies.py` and `factory.py`.

- [ ] Write the route test first using a dependency override. Assert the exact JSON shape for a signal carrying all five brief slots, source standing, coarse location precision, and attached event scores. Assert none of `raw_text`, `summary`, `prompt`, `model`, or patient fields appears anywhere in serialized JSON.
- [ ] Add bounds tests: default `hours=48&limit=50`; reject `hours=0`, `hours=169`, `limit=0`, and `limit=101` with 422.
- [ ] Define `RadarSourceResponse`, `RadarLocationResponse`, `RadarEventContextResponse`, `RadarItemResponse`, and `RadarResponse` with `ConfigDict(from_attributes=True)`, using existing enum types and `BriefPoint`. `RadarResponse` contains `items`, `window_start`, `window_end`, `hours`, and `limit`.
- [ ] Add `get_radar_page(hours, limit)` to dependencies. Capture one UTC `now`, open `session_scope`, and call `query_radar`; route code must only validate/serialize.
- [ ] Include the router in `factory.py` and run `uv run pytest apps/api/tests/test_radar.py -v`; expect green.
- [ ] Tick Task 5 and commit: `feat: expose the recent signal radar API`.

## Task 6: Expose `GET /api/v1/admin/pipeline-runs`

**Files:** create `routes/admin_pipeline.py` and `apps/api/tests/test_admin_pipeline.py`; modify `dependencies.py` and `factory.py`.

- [ ] Write an exact response test for running/stale, succeeded, and failed runs. A failure contains only `stage` and nullable `error`; the response contains no exception message, key, URL, article content, or controls.
- [ ] Test default `limit=20`, valid maximum 50, and 422 for 0 or 51.
- [ ] Add `PipelineFailureResponse`, `PipelineRunItemResponse`, and `PipelineRunListResponse`, plus `get_pipeline_run_page(limit)`. Pass `settings.gdelt_poll_interval_minutes` as `stale_after_minutes`; do not read `.env` inside the route.
- [ ] Keep the route GET-only and include it in `factory.py`.
- [ ] Run `uv run pytest apps/api/tests/test_admin_pipeline.py -v`; expect green.
- [ ] Tick Task 6 and commit: `feat: expose read-only pipeline monitoring`.

## Task 7: Regenerate and lock the API contracts

**Files:** modify `test_openapi.py`, `packages/contracts/openapi.json`, and `packages/contracts/src/index.d.ts`.

- [ ] First update `test_openapi_exposes_public_routes` to require `/api/v1/radar` and `/api/v1/admin/pipeline-runs`; run it and observe failure before regenerating.
- [ ] Add schema assertions that radar brief points, event scores, location precision, pipeline counts, and failure type are present, while `raw_text` is absent from the radar schema.
- [ ] Run `corepack pnpm contracts:generate` using the repository script, then `corepack pnpm contracts:check` and `uv run pytest apps/api/tests/test_openapi.py -v`.
- [ ] Inspect the generated TypeScript declaration; never edit it by hand.
- [ ] Tick Task 7 and commit: `feat: publish radar and monitor contracts`.

## Task 8: Strictly validate radar responses in the web client

**Files:** create `apps/web/src/lib/api-radar.ts` and `api-radar.test.ts`.

- [ ] Derive exported TypeScript aliases from `components["schemas"]` in `@episignal/contracts`; do not duplicate the response interface manually.
- [ ] Write tests for valid `ready`, thrown/non-2xx `unavailable`, and malformed-success `unavailable`. Malformed cases must include: four brief slots, slots out of order, confidence outside 0–1, half-null coordinates, event present with `none`, missing event with `attached`, and an unsafe/non-HTTP(S) source URL.
- [ ] Implement small type guards for records, enums, ISO datetimes, UUID strings, finite numeric ranges, exactly ordered slots, safe URLs, and cross-field invariants. Reject the whole response on one invalid item.
- [ ] `getRadar(hours=48, limit=50)` calls `${API_URL}/api/v1/radar?...` with `cache: "no-store"` and returns the same `loading | ready | unavailable` state vocabulary used by the current page.
- [ ] Run `corepack pnpm --filter @episignal/web test -- src/lib/api-radar.test.ts`; expect green.
- [ ] Tick Task 8 and commit: `feat: validate radar responses in the web client`.

## Task 9: Add only the map dependencies and pure marker helpers

**Files:** modify `apps/web/package.json`, `pnpm-lock.yaml`; create `signal-map.tsx` and `signal-map.test.tsx`.

- [ ] Run `corepack pnpm --filter @episignal/web add maplibre-gl` and `corepack pnpm --filter @episignal/web add -D @types/geojson`. Add no other package.
- [ ] Before instantiating MapLibre, export pure `markerFeatures(items)` and `precisionLabel(precision)` helpers. Tests assert unresolved/half-null coordinates never become features, longitude/latitude order is correct, each feature retains signal id and explicit precision, and marker size/color metadata never implies a finer precision.
- [ ] Use one GeoJSON `FeatureCollection<Point, MarkerProperties>` derived from radar items; no client-side source/location join.
- [ ] Run the focused map helper tests; expect green.
- [ ] Tick Task 9 and commit: `feat: derive honest radar marker data`.

## Task 10: Mount a small resilient MapLibre component

**Files:** modify `signal-map.tsx` and `signal-map.test.tsx`.

- [ ] Write a component test with `maplibre-gl` mocked at the module boundary. Assert one map instance, Carto Positron style, navigation controls, a GeoJSON source/layer after load, cleanup on unmount, and `Map unavailable.` after a map error. Do not test WebGL internals.
- [ ] Implement `SignalMap` as a client component. Props: `items`, `selectedId`, `onSelect`. Keep one map instance in a ref; update source data when items change; click calls `onSelect(id)`; selection changes marker styling and flies only when coordinates exist.
- [ ] The map region has an accessible name and a textual coverage summary. The list remains the complete accessible representation; do not attempt to make every canvas marker a parallel accessibility tree.
- [ ] Import `maplibre-gl/dist/maplibre-gl.css` from the client component or root layout in the supported Next.js 16 location confirmed from local docs.
- [ ] Run `corepack pnpm --filter @episignal/web test -- src/components/signal-map.test.tsx`; expect green.
- [ ] Tick Task 10 and commit: `feat: render recent signals on MapLibre`.

## Task 11: Replace the homepage with the radar map and list

**Files:** rewrite `home-shell.tsx` and `home-shell.test.tsx`.

- [ ] Replace the old raw-evidence fixtures with a five-slot radar fixture and write tests for:
  - loading, unavailable, and empty messages with no synthetic cards;
  - English title and all five slot texts in fixed order;
  - official/media plus credibility, separate event verification, location precision, and AI extraction confidence labels;
  - unmatched and ambiguous event text;
  - source link uses `target="_blank"` and `rel` containing `noreferrer`;
  - raw text and publisher headline are absent;
  - coordinate coverage says plotted vs unresolved counts;
  - clicking a card selects its marker; marker selection focuses and scrolls the matching card.
- [ ] Implement the approved desktop/mobile order: masthead, concise product statement, large map, window/coverage summary, ranked cards, evidence-before-claims note. The same `RadarItem[]` is passed to the map and rendered as cards.
- [ ] Use a ref map keyed by item id. Guard `scrollIntoView` for jsdom. A card without coordinates remains selectable but does not request map movement.
- [ ] Keep scores distinct and label `early_signal_score` as surveillance interest and `evidence_score` as evidence support. Never format them into one badge.
- [ ] Run `corepack pnpm --filter @episignal/web test -- src/components/home-shell.test.tsx`; expect green.
- [ ] Tick Task 11 and commit: `feat: turn the homepage into the signal radar`.

## Task 12: Wire server fetching, loading, responsive CSS, and build safety

**Files:** modify `app/page.tsx`, `app/loading.tsx`, and `app/globals.css`.

- [ ] Add or update tests so the shell loading state receives `apiStatus="loading"` and `radar.status="loading"`.
- [ ] In `page.tsx`, fetch API health and radar in parallel. Remove `getEvidenceFeed` from the homepage only; keep `/api/v1/signals` and its client module intact as the evidence seam.
- [ ] Update CSS within the established editorial variables. Required assertions by inspection/build: map has a stable height; cards use normal document flow; at `<= 720px` the map spans available width and the list stays visible; focus rings remain; uncertainty never relies on color alone; long titles/URLs wrap.
- [ ] Run all web tests, `corepack pnpm --filter @episignal/web typecheck`, `corepack pnpm --filter @episignal/web lint`, and `corepack pnpm --filter @episignal/web build`.
- [ ] Start the production build locally and perform one real-browser smoke: homepage loads, MapLibre mounts, a marker can select its card, narrow viewport keeps map and list usable, and disabling WebGL/map loading leaves source links usable. Record observations for Task 15; do not add Playwright or another dependency.
- [ ] Tick Task 12 and commit: `feat: make the radar responsive and resilient`.

## Task 13: Strictly validate pipeline history in the web client

**Files:** create `api-pipeline.ts` and `api-pipeline.test.ts`.

- [ ] Derive types from generated contracts. Test ready/empty/unavailable and malformed-success rejection, including negative counts, unknown status or stage, invalid dates, error payload fields beyond `stage`/`error`, and a stale flag on a non-running row.
- [ ] Implement strict guards and `getPipelineRuns(limit=20)` with `cache: "no-store"`. Reject the whole response rather than partially trusting it.
- [ ] Run `corepack pnpm --filter @episignal/web test -- src/lib/api-pipeline.test.ts`; expect green.
- [ ] Tick Task 13 and commit: `feat: validate pipeline monitoring responses`.

## Task 14: Build the read-only pipeline monitor page

**Files:** create `components/pipeline-monitor.tsx`, its test, and `app/admin/pipeline/page.tsx`; modify CSS.

- [ ] Test loading, unavailable, empty, succeeded, running, stale-running, and failed states. Assert chain, trigger, timestamps, stage counts, backlog, stage name, and exception type render. Assert there is no button, form, retry action, mutation request, secret, or error message.
- [ ] Render newest runs as a semantic table on wide screens and readable stacked rows on narrow screens using CSS only. Text must distinguish `Running`, `Succeeded`, `Failed`, and `Running — stale`; a failed run with some successful stage counts may say `Failed after partial progress`, but do not invent a fourth API status.
- [ ] Fetch in the server page and pass the state into `PipelineMonitor`. Add a normal link back to the radar; do not add admin controls to the public masthead.
- [ ] Run the focused test, then all web tests and build.
- [ ] Tick Task 14 and commit: `feat: show read-only pipeline health`.

## Task 15: Review, full gate, live proof, and completion report

**Files:** create `docs/reports/2026-08-28-subproject-e-report.md`; update `STATUS.md` task tick and verified baseline only.

- [ ] Load `code-review` and review the entire diff from `9294ae4...HEAD` against the design and this plan. Fix only hard findings, test-first. Pay special attention to raw-text leakage, source/event wording, ambiguous links, null coordinates, safe URLs, query bounds, map cleanup, and controls accidentally entering the monitor.
- [ ] Load `verify-and-stop`. Run `corepack pnpm verify` once from a clean tree candidate. Paste the real untruncated summary, including Python/web test counts, lint/format/type/contracts/build results and exit code, into the report. If it fails, fix and rerun; report only the final passing run plus any material deviations.
- [ ] Run `corepack pnpm db:check`.
- [ ] Against the live API/database, call `/api/v1/radar?hours=168&limit=10` (168 hours is allowed only to make live proof likely). Record one real item's id, English title, five ordered slots, safe source URL, source standing, location precision, and whether event context is none/attached/ambiguous. Do not paste raw text or patient data. Confirm no forbidden keys occur in the JSON.
- [ ] Open `/` at desktop and mobile widths and `/admin/pipeline`. Record map/list equivalence, external source navigation, honest unresolved behavior if present, and counts-only pipeline history. If the live 48-hour window is empty, record that honest state and use the bounded 168-hour API proof; do not create sample data.
- [ ] Run `git diff --check 9294ae4...HEAD` and `git status --short`. The tree must be clean after committing the report.
- [ ] Tick Task 15, update the verified baseline to the actual gate commit, and commit: `docs: report signal radar verification`.
- [ ] Hand back to the planner. Do **not** mark `E` verified and do not start `G`, `H`, or `M`.

---

## Worker handoff

Implement Tasks 1–15 exactly in order. The visible MVP arrives at Task 11; keep moving through monitoring and the full gate because roadmap item `E` is not complete without both. If a test exposes a design mismatch, stop and report the exact file/test/result rather than changing the contract.
