# Story Clustering, Event Matching, and Dual Scoring — Design

**Date:** 2026-08-28
**Status:** Approved
**Item:** `D2a`
**Depends on:** `D1` geocoding (`docs/superpowers/specs/2026-08-27-geocoding-design.md`)
**Followed by:** `D2b` embedding similarity and LLM escalation for ambiguous matches

## Goal

Turn geocoded signals into events. Group signals that report the same outbreak,
attach each group to an existing event or create a new one, compute the two
scores separately, and record every reported figure as a new observation.

`D2a` is entirely deterministic. It makes no model call, opens no socket, and
produces the same events from the same rows every time. `D2b` will add embedding
similarity and LLM escalation for the cases `D2a` deliberately refuses.

## Position

`D2a` is the first and only writer of `events`, `event_signals`,
`event_observations`, and `event_locations`. Everything in Band 3 of
`ROADMAP.md` is blocked on it, because until it runs those four tables are empty.

It reads signals at `processing_status = 'geocoded'` and advances them to
`'matched'`, or to `'needs_review'` when it refuses to decide.

## Vocabulary

`CONTEXT.md` is the naming authority and this design does not extend it.

A **story cluster** is a working grouping of signals within one run. It is not
an event and it is not persisted: once its signals are attached to an event,
`event_signals` is the durable record and the cluster has no further meaning.
This is why no `story_clusters` table exists. `CONTEXT.md` reserves *cluster* as
a word to avoid for events, and that stands; a story cluster is a step inside a
pass, never a thing the product shows.

## Decisions

### Scores are deterministic weighted formulas

Both scores are pure functions of stored fields, with weights in configuration.
A score a user cannot have explained to them is a number the product cannot
stand behind, and `CONTEXT.md` is explicit that a model's confidence is one
input among several and never a reason on its own.

### Both scores are `0–1`

The foundation migration gave `attention_score` the range `0–100` and
`confidence_score` the range `0–1`. Two scales invite every consumer to compare
one against the other. `D2a` puts both on `0–1` and leaves formatting to the UI.

### The score columns are renamed, not shadowed

`attention_score` becomes `early_signal_score` and `confidence_score` becomes
`evidence_score`, with their check constraints renamed and the early-signal range
widened to `0–1`. The table is empty, so no data moves. After this migration the
old names cannot be written, which is the point: `CONTEXT.md` is the naming
authority or it is decoration.

### Ambiguity refuses rather than guesses

`D1` established the house rule: when the specific answer is ambiguous, do not
tie-break. `D2a` applies the same rule to matching.

| Candidate events at or above the accept threshold | Outcome |
| --- | --- |
| Exactly one | Attach the cluster to it. |
| None | Create a new event. |
| Two or more | Attach to nothing, create nothing, route the cluster's signals to `needs_review`. |

Creating a new event when nothing matches is correct and is what Phase 1 spec
§55 Step 6 asks for: a temporary duplicate event is recoverable, a false merge
corrupts history. Creating a *third* event when a cluster matches two existing
ones is not conservative — it is a guess wearing a different hat — so that case
goes to a human instead. `D2b` is where those cases get a better answer.

### Precision governs which spatial comparison is legal

Two locations are compared at the coarsest precision they both possess. Two
`place`-precision locations are compared by distance. If either side is
`admin1`-precision, the comparison is on the administrative code, never on
distance, because a province centroid is not a point in the world. If either
side is `country`-precision, only the country code is compared. An `unresolved`
location contributes nothing and never blocks a match.

Measuring the distance between a town and a province centroid would silently
manufacture a fact the gazetteer refused to state.

### A signal with no disease is not clustered

Clustering requires an identical `disease_id`. A geocoded signal that carries
none cannot be matched conservatively, so it goes to `needs_review` rather than
into a cluster held together by geography alone.

## Architecture

The `geocode` package's shape is reused, because it works and because a worker
already knows it. Decision modules are pure; one module touches the database.

```text
events/documents.py    contracts crossing the seams        pure
events/cluster.py      story clustering                    pure
events/match.py        candidate scoring and the decision  pure
events/score.py        the two scores, verification status  pure
events/protocol.py     the EventRepository boundary        pure
events/repository.py   the only SQLAlchemy in D2a
events/assemble.py     run_event_assembly, orchestration only
event_runner.py        CLI entry point
```

`cluster.py`, `match.py`, `score.py`, and `documents.py` import neither
SQLAlchemy nor httpx, and a seam test asserts it, as `test_geocode_seams.py`
does for `D1`.

## Clustering

Within one run, signals are grouped by single-link agglomeration over a
compatibility predicate. Two signals are compatible when all three hold:

1. **Same disease.** `disease_id` is equal and not null.
2. **Temporally compatible.** The difference between their `published_at` values
   is within the configured window, default 14 days. A signal with no
   `published_at` falls back to `first_seen_at`.
3. **Spatially compatible.** Their primary locations agree at the coarsest
   precision both possess, per the rule above. The distance threshold for two
   `place`-precision locations is configurable, default 50 km, measured on the
   PostGIS geography type already in use.

Single-link is chosen deliberately: it errs toward larger clusters of the same
disease in the same place, and the conservative gate that follows is at the
matching step, where the irreversible decision actually lives.

## Matching

For each cluster, candidate events are retrieved where the disease matches, the
event is spatially compatible with the cluster's representative location, and the
event was updated within the configured recency window, default 90 days.

A match score in `0–1` is computed from weighted components: disease identity,
spatial agreement at the coarsest shared precision, temporal overlap with the
event's existing signal span, and location-precision quality. The accept
threshold defaults to `0.70` and lives in configuration. The score is stored on
`event_signals.match_score`, so every attachment can be explained afterwards.

## Scoring

Both scores are computed after attachment, from the event's full signal set.

**`early_signal_score`** — how interesting this is for surveillance: recency of
the newest signal, velocity of signals per day, distinct source count, distinct
administrative areas touched, and mean location precision.

**`evidence_score`** — how strongly it is supported: presence of an official
source, the credibility tier mix, the number of grounded observations, agreement
between successive reported totals, and mean extraction confidence as a minor
term.

Each component is normalized to `0–1` and saturates rather than growing without
bound. Weights are configuration and sum to one. Neither score reads the other.

**`verification_status`** is derived, not scored: `officially_confirmed` when any
attached signal's source has `is_official`, otherwise `high_credibility` when any
source is tier `high`, otherwise `signal`. No model confidence can raise it.

## Observations

Every newly attached signal that carries grounded counts produces exactly one new
row in `event_observations`, holding its event, its signal, the counts, the
`observation_date` taken from the extraction's `data_as_of` or `event_date`, the
`reported_at` taken from the signal's `published_at`, and the extraction
confidence.

Rows are inserted and never updated. Re-running the pass does not write a second
observation for a signal already attached to that event; the uniqueness of
`(event_id, signal_id)` in `event_signals` is what makes the pass idempotent.

## Locations

On event creation, the cluster's resolved locations are copied into
`event_locations` with their roles, precision-derived coordinates, and geocoding
provenance. On attachment, locations not already present on the event are added,
compared on `(country_code, admin1, admin2, place_name, location_role)`. Nothing
is deleted and nothing is overwritten.

## Migration

`20260828_0007_event_scores`:

- rename `events.attention_score` to `early_signal_score`;
- rename `events.confidence_score` to `evidence_score`;
- drop `attention_score_range` and add `early_signal_score_range` as `0–1`;
- drop `confidence_score_range` and add `evidence_score_range` as `0–1`.

The downgrade restores both names and both original ranges. The table is empty at
the time of the migration, so both directions are lossless.

## Acceptance

- A geocoded signal reaches `processing_status = 'matched'` attached to exactly
  one event, with a stored `match_score`.
- Two signals reporting the same disease in the same place within the window land
  on one event; two signals reporting the same disease in different countries do
  not.
- A cluster matching two events at or above the threshold creates nothing and
  leaves its signals at `needs_review`.
- A geocoded signal with no `disease_id` reaches `needs_review` and no event.
- `early_signal_score` and `evidence_score` are both within `0–1`, are computed
  independently, and no code path derives one from the other.
- An event whose only sources are informal media never reaches
  `officially_confirmed`.
- Re-running the pass over already matched signals writes no duplicate
  `event_signals` and no duplicate `event_observations`.
- The migration upgrades and downgrades cleanly against the live database.
- `cluster.py`, `match.py`, `score.py`, and `documents.py` import no database or
  network driver.
- `corepack pnpm verify` is green.

## Out of scope, deliberately

- Embedding similarity and LLM escalation for ambiguous matches. That is `D2b`.
- Event titles, slugs, and `ai_summary` beyond a deterministic placeholder. The
  public presentation of an event belongs to Band 3.
- Merging or splitting events after the fact. An operator tool for that is a
  later item; `D2a` only ever creates and attaches.
