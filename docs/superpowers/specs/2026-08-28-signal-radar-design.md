# Signal Radar — Design

**Date:** 2026-08-28
**Status:** Approved
**Item:** `E`
**Depends on:** `C2`, `D1`, `D2a`, `L`
**Phase 1 spec:** §26–§29 homepage and result card, §42–§44 operations

## Goal

Turn the verified pipeline into a usable product surface. A reader opening `/`
sees recent early signals on a world map and in a matching ranked list, can tell
what is known and uncertain, and can open the publisher's original report.

`E` also adds a small read-only pipeline monitor so the operator can tell
whether the radar is fresh. It does not add pipeline controls, review actions,
search, event pages, or export.

## Position

The existing homepage is an evidence-browser proof. It exposes source titles,
raw text, timestamps, and links through `GET /api/v1/signals`. That route remains
the raw evidence seam.

The radar is a different read model. It combines a signal's C2 extraction,
source standing, resolved location, and optional attached-event context. It gets
its own endpoint rather than widening the evidence route until one response has
two meanings.

The radar is signal-first. Matched signals may carry event scores and
verification status, but an extracted signal does not disappear merely because
no event has been created yet. This keeps the product useful while event
coverage is sparse and preserves the distinction between reporting and the
real-world event being reported.

## Chosen architecture

### A dedicated radar read module

Create `packages/backend/src/episignal_backend/radar.py` as the read boundary.
It owns frozen read models and SQLAlchemy queries for:

- recent radar signals;
- their representative resolved location;
- optional attached-event context;
- recent pipeline runs for monitoring.

Routes depend on injectable callables in `apps/api/src/episignal_api/dependencies.py`,
matching the existing evidence route. Route modules validate the read models
into response contracts; they do not assemble domain meaning themselves.

### Two HTTP endpoints

`GET /api/v1/radar?hours=48&limit=50`

- `hours`: integer, 1–168, default 48;
- `limit`: integer, 1–100, default 50;
- returns recent radar items and the effective window;
- contains no raw article body.

`GET /api/v1/admin/pipeline-runs?limit=20`

- `limit`: integer, 1–50, default 20;
- returns counts-only pipeline history;
- exposes no key, prompt, article body, exception payload, or patient-level
  information;
- is read-only. Phase 1 has no accounts or permissions, so this is operational
  visibility, not a control plane.

### One product read on the web

The Next.js homepage fetches API health and the radar response in parallel. The
same radar items drive both map markers and cards. There is no separate location
request and no client-side join that can drift from the list.

`/admin/pipeline` fetches the pipeline-run endpoint and renders a compact table.
It has no mutations.

## Radar contract

One radar item contains:

```text
id: UUID
title_english: string
brief: exactly five ordered BriefPoint values
signal_type: SignalType
processing_status: ProcessingStatus
published_at: datetime | null
first_seen_at: datetime
source:
  name: string
  url: string
  is_official: boolean
  credibility_tier: CredibilityTier
extraction_confidence: float 0–1
location: RadarLocation | null
event_context_status: "none" | "attached" | "ambiguous"
event: RadarEventContext | null
```

`RadarLocation` contains:

```text
role: LocationRole
precision: Precision
label: string
country_code: string | null
latitude: float | null
longitude: float | null
```

`RadarEventContext` contains:

```text
public_id: string
verification_status: VerificationStatus
early_signal_score: float | null
evidence_score: float | null
```

The API returns the C2 brief as structured slots. It never reconstructs the
brief from `signals.summary`, and the browser never parses newline text.

## Selection and ranking

The radar selects signals when all are true:

1. `ai_extraction` carries `extraction_schema_version = 2`;
2. the stored extraction parses through `StoredExtractionPayload`;
3. the effective timestamp is inside the requested window;
4. processing status is `extracted`, `geocoded`, `matched`, or `published`;
5. the row is not a duplicate.

Effective timestamp is `published_at` when present, otherwise `first_seen_at`.

Ordering is deliberately simple and explainable:

1. effective timestamp descending;
2. attached event `early_signal_score` descending, nulls last;
3. signal UUID descending for deterministic ties.

Recency is primary. Heat breaks ties; it does not override a newer signal. The
API returns `early_signal_score` and `evidence_score` separately and creates no
blended confidence or vanity score.

## Representative location

A signal may have several `signal_locations`. Select one for the map:

1. consider `primary` locations first;
2. otherwise consider every role;
3. choose the highest recorded precision in this order: `place`, `admin2`,
   `admin1`, `country`, `unresolved`;
4. break equal-precision ties by stable location UUID, never population or
   nearest-looking coordinates.

The label uses the resolved name when present, then the extracted place,
administrative area, or country name. Precision remains a separate field.

An unresolved location has null coordinates and appears on its card as
unresolved. It never becomes a marker. A country or province centroid remains
plottable, but the marker and text identify its coarse precision.

## Event context

The radar left-joins through `event_signals`. No attached event means `event` is
null, not an empty or invented event.

The D2a writer intends one event per signal. `event_context_status` is `none`
when there is no link, `attached` when exactly one event is linked, and
`ambiguous` when stored data links several events. An ambiguous item returns a
null `event` rather than choosing one silently. Resolving that data belongs to
matching or review work, not the read path.

## Uncertainty presentation

Cards and map popovers show separate facts rather than one synthetic badge:

- **Source:** official or media, plus the stored credibility tier;
- **Verification:** event verification status, or “Not yet matched to an
  event” when context is `none`; ambiguous context says “Multiple event links
  require review”;
- **Location:** place, district, province, country, or unresolved;
- **Extraction:** model confidence as a percentage, labelled “AI extraction
  confidence.”

Color may reinforce these labels but never replace their text. “Official”
describes the publisher. Only `verification_status` can say an event is
officially confirmed.

## Homepage

The current homepage becomes the radar rather than linking to a second page.

Desktop order:

1. masthead and short product explanation;
2. large map of the requested window;
3. window/coverage summary;
4. ranked cards driven by the same items;
5. evidence-before-claims note.

Mobile order is the same. The map spans the viewport width; the summary becomes
a normal block below it rather than hiding the list in a modal sheet.

Each card shows:

- English title;
- effective time and source name;
- five brief slots in fixed order;
- separate uncertainty labels;
- representative location text;
- “View original source” link.

The publisher headline and raw text remain available through the evidence API,
but the public radar does not display full raw text.

Selecting a marker highlights and scrolls to its card. Selecting a card focuses
the marker when it exists. The list remains the complete accessible equivalent
of the map.

## Map implementation

Use `maplibre-gl` directly in one small client component. Reuse the precision
vocabulary, marker sizing idea, and truthful pending/error states from
`feat/map-hero`; do not merge the branch or vendor its 2,232-line generic map
component.

Use the existing Carto Positron public style already proven by that branch.
Map failure leaves the ranked list usable and displays “Map unavailable.” The
map never blocks the page's evidence links.

Only add dependencies the chosen component needs: `maplibre-gl` and GeoJSON
types. Do not add a generic UI kit, icon library, class-name framework, or map
abstraction layer.

## Pipeline monitor

`/admin/pipeline` shows the newest runs first with:

- chain and trigger;
- status;
- started and finished timestamps;
- stage counts;
- backlog counts;
- failed stage name and exception type only.

The page distinguishes running, succeeded, partial, and failed states in text.
It shows a stale-running warning when a run remains `running` beyond twice its
configured schedule interval. It provides no retry button, scheduler controls,
or raw error payload.

## Failure and empty states

- API unavailable: stable page shell, explicit unavailable message, no cached or
  synthetic markers.
- No signals in window: empty map and “No recent signals in this window.”
- Some signals unresolved: cards remain; coverage summary states how many lack
  coordinates.
- Map style or WebGL unavailable: list remains complete; map region explains the
  failure.
- Pipeline history empty: monitoring page says no runs have been recorded.
- Malformed API response: web client rejects the whole response and shows the
  unavailable state rather than partially trusting it.

## Testing seams

Tests exercise public boundaries, not implementation details:

1. `query_radar` with a fake session proves window filtering, duplicate
   exclusion, deterministic ranking, representative location, tolerant stored
   extraction reading, and ambiguous-event omission.
2. FastAPI route tests prove query bounds and exact OpenAPI response shape.
3. Generated contract checks prove Python and TypeScript agree.
4. Web client tests prove strict response validation and unavailable handling.
5. Homepage component tests prove titles, five slots, uncertainty text, source
   links, empty/loading/unavailable states, and accessible map/list equivalence.
6. Map component tests cover marker filtering and precision metadata without
   requiring WebGL; one browser-level smoke check covers MapLibre mounting.
7. Pipeline monitor query, route, client, and page tests prove counts-only data
   and honest states.

These are the agreed TDD seams for the implementation plan.

## Privacy and security

- Radar response contains no `raw_text`, prompt, model request, key, exception
  message, or patient-level field.
- All displayed model prose already passed C2 privacy validation.
- URLs come from stored source records and render with safe external-link
  attributes.
- Pipeline failures expose exception type only, matching runner logging policy.
- Routes are read-only and use bounded query parameters.

## Acceptance

1. `/` renders real schema-v2 signals from the last 48 hours on a MapLibre map
   and in a matching ranked list.
2. Every card carries the English title, five ordered brief slots, separate
   uncertainty labels, location precision, and original-source link.
3. Unmatched and unresolved signals remain visible without invented event or
   coordinate data.
4. `early_signal_score` and `evidence_score` remain distinct in API and UI.
5. Map, list, empty, loading, unavailable, and mobile states are tested and
   usable without synthetic data.
6. `/admin/pipeline` renders recent counts-only pipeline history and no controls.
7. OpenAPI generation, TypeScript contracts, Python tests, web tests, lint,
   types, and production build pass through `corepack pnpm verify`.
8. Completion report quotes the real gate output and a live radar response with
   at least one source link and one location-precision example.

## Out of scope

- embedding or LLM event-match escalation (`D2b`);
- full public event API (`G`);
- final homepage/event-feed refinement (`H`);
- event pages and observation timelines (`I`);
- search (`J`);
- export (`K`);
- review actions (`M`);
- alerts, scheduler controls, accounts, permissions, or mutations;
- clustering markers, heatmaps, animations, custom basemap hosting, and dark
  mode;
- redesigning the established editorial visual system.
