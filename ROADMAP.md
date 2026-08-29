# EpiSignal Roadmap — Phase 1 to MVP

The long road. This file says what the whole build is and how far along each
piece is. It does not say what is happening today; [STATUS.md](STATUS.md) says
that.

- **Where are we now:** [STATUS.md](STATUS.md)
- **Who writes what:** [docs/agents/workflow.md](docs/agents/workflow.md)
- **Active briefing:** [HANDOFF.md](HANDOFF.md)
- **Naming authority:** [CONTEXT.md](CONTEXT.md)
- **Full requirements:** [EpiSignal_Phase1_AI_Agent_Handoff.md](EpiSignal_Phase1_AI_Agent_Handoff.md)

## How to read a row

Every item has a stable identifier, a one-sentence condition that ends it, the
items it depends on, a status, and links to the artifacts it produced.

Identifiers `A` through `F` mean exactly what
[the GDELT layer architecture](docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md)
says they mean. `P0` through `P3` are retrofitted onto work that predates that
document. `G` onward continues the sequence for work it never covered.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| `not-started` | No design work has begun. |
| `designing` | Brainstorming is under way; no spec is committed. |
| `designed` | A spec is committed under `docs/superpowers/specs/`. |
| `planned` | An implementation plan is committed under `docs/superpowers/plans/`. |
| `building` | Tasks are being executed; some are ticked. |
| `verified` | Every task is done, `corepack pnpm verify` is green, and a report is committed. |
| `blocked` | Progress needs a decision or an upstream item. |

An item is never `verified` without the verification output recorded in its
report. That gate is not negotiable and is not waived for documentation-only or
small items.

## Progress

```text
Band 0  Foundation              [#]      1/1  verified
Band 1  Official ingestion      [###]    3/3  verified
Band 2  GDELT discovery layer   [######--] 6/8  D2b and F remain
Band 3  Product surface         [#-----] 1/6  E verified; G, H, I, J, K remain
Band 4  Operations              [#--]    1/3  M and N remain
Band 5  Acceptance              [-]      0/1
```

---

## Band 0 — Foundation

| ID | Item | Ends when | Depends on | Status |
| --- | --- | --- | --- | --- |
| `P0` | Repository, schema, contracts, shell | A versioned PostgreSQL/PostGIS schema, a FastAPI service, generated OpenAPI and TypeScript contracts, and an honestly empty web shell exist and verify green. | — | `verified` |

Artifacts: [spec](docs/superpowers/specs/2026-08-26-foundation-design.md) ·
[plan](docs/superpowers/plans/2026-08-26-foundation.md)

---

## Band 1 — Official source ingestion

| ID | Item | Ends when | Depends on | Status |
| --- | --- | --- | --- | --- |
| `P1` | WHO Disease Outbreak News ingestion | WHO DON documents are stored as signals with canonical URLs, separated timestamps, and a resolved source. | `P0` | `verified` |
| `P2` | ECDC Epidemiological Update ingestion | ECDC updates ingest through the same storage boundary as WHO DON. | `P1` | `verified` |
| `P3` | Signal evidence browser | `GET /api/v1/signals` returns stored evidence and the homepage renders it with working source links and an honest coverage label. | `P1` | `verified` |

Artifacts:
`P1` [spec](docs/superpowers/specs/2026-08-26-who-don-ingestion-design.md) ·
[plan](docs/superpowers/plans/2026-08-26-who-don-ingestion.md) —
`P2` [spec](docs/superpowers/specs/2026-08-26-ecdc-epi-update-ingestion-design.md) —
`P3` [spec](docs/superpowers/specs/2026-08-26-signal-evidence-browser-design.md)

---

## Band 2 — GDELT discovery layer

Umbrella architecture and shared invariants:
[docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md](docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md).

| ID | Item | Ends when | Depends on | Status |
| --- | --- | --- | --- | --- |
| `A` | Discovery connector, query library, provenance schema | A GDELT-discovered signal is stored with its real publisher, original URL, and separated timestamps. | `P0` | `verified` |
| `B` | Stage 0: deduplication and rule filtering | Syndicated copies and obviously irrelevant articles are rejected before any AI call. | `A` | `verified` |
| `C` | AI classification, extraction, escalation, cost logging | Relevant signals carry schema-validated epidemiological extraction, and every AI request is costed. | `B` | `verified` |
| `C2` | English title and the five-slot brief | Every extraction carries an English title and a five-bullet brief in fixed slot order, with source spans left in the language the publisher wrote. | `C` | `verified` |
| `D1` | Geocoding of extracted places | Extracted places resolve against the gazetteer into `signal_locations` with PostGIS geometry and recorded precision, coarsening rather than tie-breaking on ambiguity. | `C` | `verified` |
| `D2a` | Story clustering, event matching, dual scoring — deterministic | Signals group into story clusters, clusters match or create events, `early_signal_score` and `evidence_score` are computed separately, and observations are recorded. No model call. | `D1` | `verified` |
| `D2b` | Embedding similarity and LLM escalation | The ambiguous matches `D2a` refuses get a better answer from embedding similarity and, where still unclear, an escalated model judgement. | `D2a` | `not-started` |
| `F` | Model benchmarking harness | Free-model selection is backed by stored measurements rather than impressions. | `C` | `not-started` |

Artifacts:
`A` [spec](docs/superpowers/specs/2026-08-27-gdelt-discovery-design.md) ·
[plan](docs/superpowers/plans/2026-08-27-gdelt-discovery.md) ·
[report](docs/reports/2026-08-27-subproject-a-report.md) —
`B` [spec](docs/superpowers/specs/2026-08-27-gdelt-stage0-filtering-design.md) ·
[plan](docs/superpowers/plans/2026-08-27-gdelt-stage0-filtering.md) ·
[report](docs/reports/2026-08-27-subproject-b-report.md) —
`C` [spec](docs/superpowers/specs/2026-08-27-ai-extraction-design.md) ·
[plan](docs/superpowers/plans/2026-08-27-ai-extraction.md) ·
[report](docs/reports/2026-08-27-subproject-c-report.md) —
`C2` [spec](docs/superpowers/specs/2026-08-28-english-brief-design.md) ·
[plan](docs/superpowers/plans/2026-08-28-english-brief.md) ·
[correction plan](docs/superpowers/plans/2026-08-28-c2-completion-corrections.md) ·
[report](docs/reports/2026-08-28-subproject-c2-report.md) —
`D1` [spec](docs/superpowers/specs/2026-08-27-geocoding-design.md) ·
[plan](docs/superpowers/plans/2026-08-27-geocoding.md) ·
[report](docs/reports/2026-08-27-subproject-d1-report.md) —
`D2a` [spec](docs/superpowers/specs/2026-08-28-story-clustering-design.md) ·
[plan](docs/superpowers/plans/2026-08-28-story-clustering.md) ·
[report](docs/reports/2026-08-28-subproject-d2a-report.md)

### Pipeline as it stands

```text
[GDELT 15m poll]  ->  A   discover_runner.py     verified
[Gate 1 filter]   ->  A   rejected_sightings     verified
[Web retrieval]   ->  A   ArticleFetcher         verified
[Gate 2 dedupe]   ->  B   dedupe_runner.py       verified
[Gate 3 AI]       ->  C   extract_runner.py      verified
[English brief]   ->  C2  backfill_runner.py     verified
[Geocoding]       ->  D1  geocode_runner.py      verified
[Clustering]      ->  D2a event_runner.py        verified
[Ambiguous match] ->  D2b ---                    not started
[Radar surface]   ->  E   radar.py + Next UI     verified
[Manual review]   ->  M   ---                    not started

[Runs it daily]   ->  L   pipeline_runner.py     verified
```

The chain runs unattended, which is what `L` was for. The extraction
configuration blocker is resolved: OpenRouter receives a strict Pydantic-derived
JSON schema with a compatibility fallback, and the refreshed ladder completed
28 live extractions with zero shape rejections. The same proof reached 32
geocoded signals and created the first 3 events. Details and the bounded backlog
requeue are recorded in the
[extraction stall fix report](docs/reports/2026-08-28-extraction-stall-fix-report.md).

`C2` gives `E` its display contract: an English title and five ordered brief
slots, with evidence spans kept in the publisher's language. `E` now renders
that shape on the signal-first radar, with event context when one exists.

---

## Band 3 — Product surface

Nothing in this band can start before `D2a`, because `events`, `event_signals`,
`event_observations`, and `event_locations` have no writer until `D2a` exists.

| ID | Item | Ends when | Depends on | Status |
| --- | --- | --- | --- | --- |
| `E` | Signal Radar API, Signal Radar UI, admin monitoring | A user sees an early signal, its uncertainty, and can open the original article. | `D2a` | `verified` |
| `G` | Public event API | Read-only events list, event detail, observations, sources, and filters are served and contract-checked. Phase 1 spec §46. | `D2a` | `not-started` |
| `H` | Homepage world map and event feed | A usable world map and list view render real events, responsive from the first commit. Phase 1 spec §26–§28. | `G` | `not-started` |
| `I` | Event page: overview, timeline, sources, data | Every claim on the page shows the source that made it, the time it was made, and the previous value. Phase 1 spec §30–§34. | `G` | `not-started` |
| `J` | Search | Structured search over disease, place, date, and status works; natural-language parsing is optional and separate. Phase 1 spec §40. | `G` | `not-started` |
| `K` | Data export | Structured export of events and observations is downloadable with provenance intact. Phase 1 spec §47. | `G` | `not-started` |

Artifacts: `E`
[spec](docs/superpowers/specs/2026-08-28-signal-radar-design.md) ·
[plan](docs/superpowers/plans/2026-08-28-signal-radar.md) ·
[report](docs/reports/2026-08-28-subproject-e-report.md)

---

## Band 4 — Operations

| ID | Item | Ends when | Depends on | Status |
| --- | --- | --- | --- | --- |
| `L` | Scheduler | Discovery, ingestion, dedupe, extraction, geocoding, and clustering run on schedule without manual invocation. Phase 1 spec §42. | `D2a` | `verified` |
| `M` | Manual review queue | Signals in `needs_review` reach a human queue and can be resolved back into the pipeline. Phase 1 spec §43–§44. | `E` | `designed` |
| `N` | SEO, performance, accessibility | The public pages meet the stated performance budget and accessibility requirements and are indexable. Phase 1 spec §48–§50. | `H`, `I` | `not-started` |

Artifacts:
`L` [spec](docs/superpowers/specs/2026-08-28-scheduler-design.md) ·
[plan](docs/superpowers/plans/2026-08-28-scheduler.md) ·
[report](docs/reports/2026-08-28-subproject-l-report.md) —
`M` [spec](docs/superpowers/specs/2026-08-29-manual-review-queue-design.md)

`L` was taken ahead of Band 3 deliberately. It depends only on `D2a`, and the
items that follow it are worth more once real events exist to build against.
`M` stays where it is: it depends on `E`, because a review queue needs a surface.

---

## Band 5 — Acceptance

| ID | Item | Ends when | Depends on | Status |
| --- | --- | --- | --- | --- |
| `Z` | MVP acceptance gate | Every criterion in Phase 1 spec §56 — data, events, UI, trust, API — is demonstrated against real reporting, and the vertical slice in §63 runs end to end. | all above | `not-started` |

---

## Beyond Phase 1

Direction, not committed scope. No rows, no status, no estimates until Phase 1
passes its acceptance gate.

**Phase 2** (Phase 1 spec §58): many more sources, multilingual and local-language
extraction, saved searches and follows, daily briefing and alerts, historical
event reconstruction, research API keys, GeoJSON and Parquet export, cross-border
spread detection, trend detection.

**Phase 3** (§59): open epidemic intelligence infrastructure — near-real-time
global surveillance, a large historical event database, citation-ready permanent
event identifiers, a public open API, and machine-assisted source reconciliation.

**Explicit non-goals for Phase 1** (§57): social media scraping, outbreak
forecasting, risk recommendations to the public, patient-level data, accounts and
permissions, native mobile applications, push and messaging alerts, genomic data.
Do not build these, and do not let a roadmap item quietly grow into one.
