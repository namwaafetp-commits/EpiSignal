# Story Clustering, Event Matching, and Dual Scoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tick each task in `STATUS.md` in the same commit as the work.

**Item:** `D2a`

**Goal:** Turn geocoded signals into events. Group signals reporting the same outbreak, attach each group to exactly one existing event or create a new one, compute `early_signal_score` and `evidence_score` separately, record every reported figure as a new observation, and advance the signal from `geocoded` to `matched`.

**Architecture:** Deterministic throughout. Single-link story clustering over a compatibility predicate of identical disease, temporal window, and precision-governed spatial agreement. Conservative matching: exactly one candidate above threshold attaches, none creates, two or more refuses and routes to review. Two independent weighted score functions, both `0–1`. Decision modules import no SQLAlchemy and no httpx; `events/repository.py` is the only module that touches the database; nothing in the sub-project touches the network or a model provider.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, PostGIS via GeoAlchemy2, Pydantic v2, pytest, ruff, mypy. Run Python through `uv run`. Run workspace scripts through `corepack pnpm`.

**Design:** `docs/superpowers/specs/2026-08-28-story-clustering-design.md`

**Base commit:** `7c78c78` plus the commit carrying `ROADMAP.md`, `STATUS.md`, `docs/agents/workflow.md`, and this plan.

---

## Environment Notes

- Bare `python` is not on `PATH`. Every Python command runs through `uv run`.
- `pnpm` is not on `PATH`. Every workspace command runs through `corepack pnpm`.
- Windows PowerShell 5.1: chain commands with `;`, never `&&`.
- Tests must open no socket and reach no live database. Tasks 1 through 21 run with no key, no network, and no database. Task 22 is the only task that touches the database.
- `apps/api/.env` names the real database. Never paste it anywhere.

## Inherited facts you must not rediscover

- `signal_locations` carries `location_role`, `precision`, `latitude`, `longitude`, a PostGIS point, `geocoding_confidence`, and `geocoding_source`. `precision` is one of `place`, `admin2`, `admin1`, `country`, `unresolved`.
- `point_4326()` in `models/event.py` returns a **Geography** type, so PostGIS distances are already in metres. Do not convert.
- `ProcessingStatus.MATCHED` already exists in `db/types.py`. Do not add it.
- `events.attention_score` is `0–100` and `events.confidence_score` is `0–1`, both nullable, both currently unwritten. `D2a` renames them.
- `event_signals` has a composite primary key of `(event_id, signal_id)`. That constraint is what makes the pass idempotent — rely on it rather than inventing a guard.
- `signals.ai_extraction` holds the `Extraction` shape from `ai/schema.py`. Counts are `GroundedCount` objects with `value` and `source_span`, and any of them may be absent.
- The gazetteer holds no place below roughly 1,000 inhabitants, so `country`-precision locations are common and must carry low weight.

## File Structure

**Created:**

| Path | Responsibility |
| --- | --- |
| `packages/backend/src/episignal_backend/events/__init__.py` | package marker |
| `packages/backend/src/episignal_backend/events/documents.py` | contracts crossing the seams |
| `packages/backend/src/episignal_backend/events/cluster.py` | story clustering, pure |
| `packages/backend/src/episignal_backend/events/match.py` | candidate scoring and the decision, pure |
| `packages/backend/src/episignal_backend/events/score.py` | the two scores and verification status, pure |
| `packages/backend/src/episignal_backend/events/protocol.py` | the `EventRepository` boundary |
| `packages/backend/src/episignal_backend/events/repository.py` | the only SQLAlchemy in the sub-project |
| `packages/backend/src/episignal_backend/events/assemble.py` | `run_event_assembly`, orchestrating protocols only |
| `packages/backend/src/episignal_backend/event_runner.py` | CLI entry point |
| `database/migrations/versions/20260828_0007_event_scores.py` | rename both score columns and their constraints |
| `packages/backend/tests/test_event_documents.py` | contract tests |
| `packages/backend/tests/test_event_cluster.py` | clustering tests |
| `packages/backend/tests/test_event_match.py` | matching decision tests |
| `packages/backend/tests/test_event_score.py` | scoring tests |
| `packages/backend/tests/test_event_protocol.py` | boundary tests |
| `packages/backend/tests/test_event_repository.py` | repository tests |
| `packages/backend/tests/test_event_assemble.py` | orchestration tests |
| `packages/backend/tests/test_event_runner.py` | runner tests |
| `packages/backend/tests/test_event_seams.py` | seam guard |

**Modified:**

| Path | Change |
| --- | --- |
| `packages/backend/src/episignal_backend/models/event.py` | renamed score columns and constraints |
| `packages/backend/src/episignal_backend/schema_check.py` | expect the renamed columns |
| `packages/backend/src/episignal_backend/config.py` | clustering, matching, and scoring settings |
| `package.json` | `match:events` script |
| `STATUS.md` | tick each task as it lands |
| `ROADMAP.md` | `D2a` to `building` at task 1 |

---

## Task 1: Contracts across the seams

**Files:**
- Create: `packages/backend/src/episignal_backend/events/__init__.py`, `events/documents.py`
- Test: `packages/backend/tests/test_event_documents.py`

- [ ] **Step 1: Write the failing test**

Assert that the contracts are frozen, reject out-of-range values, and carry no database types:

- `SignalForMatching` holds `signal_id`, `disease_id`, `source_id`, `source_is_official`, `credibility_tier`, `published_at`, `first_seen_at`, `locations`, `extraction`, and rejects a null `signal_id`.
- `LocationForMatching` holds `location_role`, `precision`, `country_code`, `admin1`, `admin2`, `place_name`, `latitude`, `longitude`, and permits null coordinates only when `precision` is `unresolved`.
- `StoryCluster` holds a non-empty tuple of `SignalForMatching` and exposes `disease_id`, `representative_location`, and `span`.
- `CandidateEvent` holds `event_id`, `disease_id`, `locations`, `first_signal_at`, `last_updated_at`.
- `MatchDecision` is one of attach, create, or refuse, and an attach decision must carry both an `event_id` and a `match_score` in `0–1`.
- `ScoreBreakdown` holds each named component and a total, and the total is within `0–1`.

- [ ] **Step 2: Implement**

Pydantic v2 models with `model_config = ConfigDict(extra="forbid", frozen=True)`, matching `ai/schema.py` and `geocode/documents.py` house style. Import only from `db/types.py` and the standard library.

- [ ] **Step 3: Commit** — `feat: add contracts for clustering, matching, and scoring`

---

## Task 2: Precision weighting

**Files:** Modify `events/cluster.py` · Test `test_event_cluster.py`

- [ ] **Step 1: Write the failing test**

`precision_weight` returns `1.0` for `place`, `0.75` for `admin2`, `0.5` for `admin1`, `0.25` for `country`, `0.0` for `unresolved`. Assert the ordering is strictly decreasing, so a future edit cannot accidentally flatten it.

- [ ] **Step 2: Implement** — a single mapping and a lookup. No branching on anything else.

- [ ] **Step 3: Commit** — `feat: weight a location by how specific it is`

---

## Task 3: Spatial compatibility at the coarsest shared precision

**Files:** Modify `events/cluster.py` · Test `test_event_cluster.py`

- [ ] **Step 1: Write the failing test**

`spatially_compatible(a, b, *, distance_km)` must:

- compare two `place`-precision locations by great-circle distance and accept only within `distance_km`;
- compare on `admin1` codes, never distance, when either side is `admin1`-precision — a town 5 km from a province centroid is **not** thereby compatible;
- compare on `country_code` only when either side is `country`-precision;
- return `False` when either side is `unresolved`, and assert this never raises;
- return `False` when country codes differ, whatever the distance.

The distance case must include a pair 5 km apart that passes and a pair 500 km apart that fails.

- [ ] **Step 2: Implement**

Determine the coarsest precision of the pair, then dispatch. Use a haversine helper in the same module; do not import a geo library and do not touch PostGIS here — this function is pure and runs without a database.

- [ ] **Step 3: Commit** — `feat: compare places only at a precision both actually have`

---

## Task 4: Temporal compatibility

**Files:** Modify `events/cluster.py` · Test `test_event_cluster.py`

- [ ] **Step 1: Write the failing test**

`temporally_compatible(a, b, *, window_days)` uses `published_at`, falls back to `first_seen_at` when `published_at` is null, and is symmetric. Assert a pair inside the window passes, a pair outside fails, and a signal with no `published_at` is compared on `first_seen_at` rather than skipped.

- [ ] **Step 2: Implement** — timezone-aware comparison only. Reject naive datetimes rather than assuming UTC.

- [ ] **Step 3: Commit** — `feat: bound a story cluster in time`

---

## Task 5: A signal with no disease is not clustered

**Files:** Modify `events/cluster.py` · Test `test_event_cluster.py`

- [ ] **Step 1: Write the failing test**

`compatible(a, b, ...)` requires equal, non-null `disease_id`. Two signals both carrying `disease_id = None` are **not** compatible with each other. Assert this explicitly — it is the case an implementer will get wrong.

- [ ] **Step 2: Implement** — the disease check first, then temporal, then spatial.

- [ ] **Step 3: Commit** — `feat: require an identical disease before grouping signals`

---

## Task 6: Single-link cluster assembly

**Files:** Modify `events/cluster.py` · Test `test_event_cluster.py`

- [ ] **Step 1: Write the failing test**

`build_clusters(signals, *, window_days, distance_km)` returns disjoint clusters covering every clusterable signal, plus the unclusterable ones separately. Assert:

- three signals where A links B and B links C but A does not link C produce **one** cluster of three (single-link is transitive by design);
- signals of different diseases never share a cluster;
- a signal with no disease appears in the unclusterable set, not in a cluster;
- the result is deterministic — same input order or shuffled, same clusters.

- [ ] **Step 2: Implement** — union-find or an explicit transitive closure. Sort the output by a stable key so the determinism test is meaningful.

- [ ] **Step 3: Commit** — `feat: group compatible signals into story clusters`

---

## Task 7: Candidate match scoring

**Files:** Create `events/match.py` · Test `test_event_match.py`

- [ ] **Step 1: Write the failing test**

`match_score(cluster, candidate, *, weights)` returns a value in `0–1` built from weighted components: disease identity, spatial agreement at the coarsest shared precision, temporal overlap with the candidate's signal span, and mean location precision. Assert:

- an identical disease in the identical place within days scores near the top;
- the same disease in a different country scores at or near zero;
- a `country`-precision-only cluster cannot reach the accept threshold on geography alone;
- weights that sum to one keep the result within `0–1`.

- [ ] **Step 2: Implement** — pure, no I/O, no clamping that hides a bug: assert internally that each component is within `0–1` before weighting.

- [ ] **Step 3: Commit** — `feat: score how well a cluster matches an existing event`

---

## Task 8: The conservative decision

**Files:** Modify `events/match.py` · Test `test_event_match.py`

- [ ] **Step 1: Write the failing test**

`decide(cluster, candidates, *, threshold, weights)` returns:

- **attach** when exactly one candidate is at or above `threshold`, carrying that event's id and its score;
- **create** when no candidate reaches `threshold`;
- **refuse** when two or more candidates reach `threshold`.

Assert the refuse case explicitly creates nothing and names no event. Assert a candidate exactly at the threshold counts as at or above it.

- [ ] **Step 2: Implement** — no tie-breaking of any kind. Do not sort and take the best; count the qualifiers.

- [ ] **Step 3: Commit** — `feat: refuse to choose between two matching events`

---

## Task 9: The early signal score

**Files:** Create `events/score.py` · Test `test_event_score.py`

- [ ] **Step 1: Write the failing test**

`early_signal_score(signals, *, now, weights)` returns a `ScoreBreakdown` in `0–1` from recency, velocity, distinct source count, distinct administrative areas, and mean location precision. Assert:

- a report from today scores higher on recency than the identical report from 30 days ago;
- five distinct sources score higher than five signals from one source;
- the component values saturate rather than growing without bound at 50 signals;
- the total never exceeds `1.0` and never falls below `0.0`.

- [ ] **Step 2: Implement** — each component a small named pure function, then a weighted sum. Saturate with a bounded curve, not a hard cap that makes 10 and 100 identical.

- [ ] **Step 3: Commit** — `feat: score how interesting an event is for surveillance`

---

## Task 10: The evidence score

**Files:** Modify `events/score.py` · Test `test_event_score.py`

- [ ] **Step 1: Write the failing test**

`evidence_score(signals, observations, *, weights)` returns a `ScoreBreakdown` in `0–1` from official-source presence, credibility tier mix, observation count, agreement between successive reported totals, and mean extraction confidence. Assert:

- one official source outscores ten informal ones on the official component;
- contradictory totals across sources lower the consistency component;
- **no code path lets either score read the other** — call both on the same input and assert changing an early-signal-only input leaves the evidence total unchanged.

- [ ] **Step 2: Implement** — same shape as task 9. `score.py` must contain no function that takes both totals.

- [ ] **Step 3: Commit** — `feat: score how strongly an event is supported`

---

## Task 11: Verification status is derived, never scored

**Files:** Modify `events/score.py` · Test `test_event_score.py`

- [ ] **Step 1: Write the failing test**

`verification_status(signals)` returns `officially_confirmed` when any source has `is_official`, else `high_credibility` when any tier is `high`, else `signal`. Assert that a set of informal sources with extraction confidence `1.0` and a perfect evidence score still returns `signal`.

- [ ] **Step 2: Implement** — a three-branch function reading source facts only. It must not accept a score argument.

- [ ] **Step 3: Commit** — `feat: derive verification status from sources alone`

---

## Task 12: The score column migration

**Files:** Create `database/migrations/versions/20260828_0007_event_scores.py` · Test `test_models.py`

- [ ] **Step 1: Write the failing test**

Assert the `Event` model exposes `early_signal_score` and `evidence_score`, exposes neither old name, and that both check constraints are named for the new columns with range `0–1`.

- [ ] **Step 2: Implement**

Upgrade renames both columns, drops `attention_score_range` and `confidence_score_range`, and adds `early_signal_score_range` and `evidence_score_range`, both `>= 0 AND <= 1`. Downgrade restores both names and both original ranges, including `0–100` for `attention_score`. Update `models/event.py` to match.

Revision id `20260828_0007_event_scores`, down revision `20260827_0006_geocoding`.

- [ ] **Step 3: Commit** — `feat: rename the event score columns to the domain names`

---

## Task 13: Schema check follows the rename

**Files:** Modify `schema_check.py` · Test `test_schema_check.py`

- [ ] **Step 1: Write the failing test** — the expected `events` columns include the two new names and neither old one.
- [ ] **Step 2: Implement** — update the expected column set.
- [ ] **Step 3: Commit** — `test: expect the renamed event score columns`

---

## Task 14: The repository boundary

**Files:** Create `events/protocol.py` · Test `test_event_protocol.py`

- [ ] **Step 1: Write the failing test**

`EventRepository` is a `Protocol` declaring `signals_to_match`, `candidate_events`, `create_event`, `attach_signal`, `record_observation`, `add_locations`, `apply_scores`, `mark_matched`, `mark_needs_review`, `commit`, and `rollback`. Assert a hand-written in-memory double satisfies it under mypy, as `test_geocode_protocol.py` does.

- [ ] **Step 2: Implement** — `Protocol` definitions and a `NoEventsToMatch`-style exception if the pass needs one. No SQLAlchemy import.

- [ ] **Step 3: Commit** — `feat: add the event storage boundary`

---

## Task 15: Selecting geocoded signals

**Files:** Create `events/repository.py` · Test `test_event_repository.py`

- [ ] **Step 1: Write the failing test**

`signals_to_match(limit, stale=False)` returns `SignalForMatching` objects for signals at `processing_status = 'geocoded'`, joined to their `signal_locations` and to their source's `is_official` and `credibility_tier`. With `stale=True` it also returns already-`matched` signals, mirroring `geocode/repository.py`'s `--stale` behaviour. Use the same test approach `test_geocode_repository.py` uses — no live database.

- [ ] **Step 2: Implement** — SQLAlchemy 2 select with explicit joins. Map rows into the pure contracts at this boundary; nothing downstream sees an ORM object.

- [ ] **Step 3: Commit** — `feat: select geocoded signals with their locations and sources`

---

## Task 16: Candidate event retrieval

**Files:** Modify `events/repository.py` · Test `test_event_repository.py`

- [ ] **Step 1: Write the failing test**

`candidate_events(cluster, *, recency_days, distance_km)` returns events with the same `disease_id`, updated within `recency_days`, and spatially plausible. Assert that spatial narrowing uses `ST_DWithin` on the geography column **only when the cluster's representative location is `place` or `admin2` precision**, and falls back to `country_code` equality otherwise — the same precision rule as task 3, enforced in SQL.

- [ ] **Step 2: Implement** — retrieval is a coarse net; the authoritative decision stays in `match.py`. Over-fetching here is correct and cheap.

- [ ] **Step 3: Commit** — `feat: retrieve candidate events without deciding between them`

---

## Task 17: Creating events and attaching signals

**Files:** Modify `events/repository.py` · Test `test_event_repository.py`

- [ ] **Step 1: Write the failing test**

- `create_event(cluster)` inserts one `events` row with a deterministic `public_id` and `slug`, the cluster's disease, its representative coordinates, and `first_signal_at` from the earliest signal.
- `attach_signal(event_id, signal_id, *, relationship_type, match_score, is_primary)` inserts one `event_signals` row.
- Attaching a signal already attached to that event does not raise and does not duplicate — assert the composite primary key is relied on rather than a pre-read.
- The first signal attached to a new event is `initial_report` and `is_primary`; later ones are `supporting_source`.

- [ ] **Step 2: Implement** — `slug` and `public_id` derived deterministically from disease, country, and the earliest signal date, so a re-run produces the same identity. No title generation beyond a plain deterministic string; presentation belongs to Band 3.

- [ ] **Step 3: Commit** — `feat: create events and attach their signals`

---

## Task 18: Observations are inserted, never updated

**Files:** Modify `events/repository.py` · Test `test_event_repository.py`

- [ ] **Step 1: Write the failing test**

`record_observation(event_id, signal)` inserts one `event_observations` row carrying the grounded counts from `signals.ai_extraction`, `observation_date` from `data_as_of` or `event_date`, `reported_at` from `published_at`, and `extraction_confidence` from the extraction. Assert:

- absent counts are stored as null, never as zero — this is the test that protects the domain;
- no `UPDATE` is ever issued against `event_observations`;
- a second pass over an already-attached signal writes no second row.

Also test `add_locations`, `apply_scores`, `mark_matched`, and `mark_needs_review` here.

- [ ] **Step 2: Implement** — insert-only. `add_locations` compares on `(country_code, admin1, admin2, place_name, location_role)` and adds what is missing, deleting nothing.

- [ ] **Step 3: Commit** — `feat: record observations without overwriting history`

---

## Task 19: The assembly pass

**Files:** Create `events/assemble.py` · Test `test_event_assemble.py`

- [ ] **Step 1: Write the failing test**

`run_event_assembly(repository, *, limit, window_days, distance_km, threshold, recency_days, weights, stale=False)` returns a result carrying `examined`, `clustered`, `events_created`, `signals_attached`, `observations_recorded`, and `refused`. Drive it entirely through an in-memory repository double. Assert:

- two compatible signals produce one event and two `event_signals` rows;
- an unclusterable signal reaches `needs_review` and no event;
- a refused cluster creates nothing and routes every one of its signals to `needs_review`;
- scores are applied once per touched event, after all attachments;
- a second run over the same data creates no new events and no new observations.

- [ ] **Step 2: Implement** — orchestration only. It calls the pure functions and the protocol. It contains no scoring arithmetic and no SQL.

- [ ] **Step 3: Commit** — `feat: add the event assembly pass`

---

## Task 20: Configuration

**Files:** Modify `config.py` · Test `test_config.py`

- [ ] **Step 1: Write the failing test**

Settings exist with documented defaults: `event_cluster_window_days = 14`, `event_cluster_distance_km = 50`, `event_match_threshold = 0.70`, `event_candidate_recency_days = 90`, `event_batch_limit`, and the two weight groups. Assert weights that do not sum to one are rejected at construction rather than silently normalized.

- [ ] **Step 2: Implement** — follow the existing `EPISIGNAL_` prefix convention.

- [ ] **Step 3: Commit** — `feat: add event assembly configuration`

---

## Task 21: The runner, the script, and the seam guard

**Files:** Create `event_runner.py`, `test_event_runner.py`, `test_event_seams.py` · Modify `package.json`

- [ ] **Step 1: Write the failing tests**

- The runner parses `--limit` and `--stale`, builds the repository, calls `run_event_assembly`, prints a one-line summary, and exits non-zero on a configuration error.
- The seam guard asserts that `events/documents.py`, `events/cluster.py`, `events/match.py`, and `events/score.py` import no `sqlalchemy`, no `geoalchemy2`, and no `httpx`, reading the modules the way `test_geocode_seams.py` does.

- [ ] **Step 2: Implement** — mirror `geocode_runner.py`. Add `"match:events": "uv run --package episignal-backend python -m episignal_backend.event_runner"` to `package.json`, and add the command to the README quality-commands list.

- [ ] **Step 3: Commit** — `feat: add the event assembly command and guard its seams`

---

## Task 22: Live database verification

**Files:** none — this task produces evidence, not code.

- [ ] **Step 1: Migrate**

```powershell
corepack pnpm db:migrate
corepack pnpm db:rollback
corepack pnpm db:migrate
```

Confirm the rollback is clean in both directions and record the revision.

- [ ] **Step 2: Run the pass against real geocoded signals**

```powershell
corepack pnpm match:events
```

Record: signals examined, clusters formed, events created, signals attached, observations recorded, clusters refused.

- [ ] **Step 3: Confirm idempotence**

Run it a second time and confirm zero new events and zero new observations. Then run with `--stale` and confirm the same.

- [ ] **Step 4: Inspect the result by hand**

Open one created event and confirm: every attached signal is reachable to its original URL, every observation names the signal that reported it, the two scores are both within `0–1` and differ from each other, and no event whose sources are all informal is `officially_confirmed`.

- [ ] **Step 5: Run the gate**

```powershell
corepack pnpm verify
```

- [ ] **Step 6: Write the report**

Write `docs/reports/2026-08-28-subproject-d2a-report.md` with the task ledger, the live run figures, and the **real** output of `corepack pnpm verify` — the test counts, not a claim that tests passed. Update the **Verified baseline** table in `STATUS.md` with the commit you ran at.

- [ ] **Step 7: Commit** — `docs: add the Sub-Project D2a completion report`

Then hand back to the planner. Do not set `D2a` to `verified` yourself.

---

## Stop conditions

Stop and report rather than improvising if any of these happen:

- A test demands that two events be merged to pass. Merging is out of scope and `D2a` never merges; the plan is wrong, not the invariant.
- The accept threshold has to move to make a test pass. Thresholds are configuration and belong in the design conversation, not in a test fixture.
- Clustering needs a similarity the extraction does not carry. That is `D2b` — embeddings — arriving early. Note it and stop.
- The live pass produces a single event containing signals from unrelated countries. That is a false merge, the one outcome this sub-project exists to prevent.
