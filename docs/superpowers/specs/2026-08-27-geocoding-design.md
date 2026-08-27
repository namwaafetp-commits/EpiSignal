# Geocoding Extracted Places — Design

**Date:** 2026-08-27
**Status:** Approved
**Sub-project:** D1 of `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md`
**Depends on:** Sub-project C (AI classification and grounded extraction), merged to `main` on 2026-08-27

## Goal

Turn the place names a signal's extraction reports into coordinates, or into an
honest statement that they could not be resolved.

This slice ends when a signal at `processing_status = 'extracted'` has one
`signal_locations` row for every location its extraction named, each row
recording both what the article said and what the gazetteer answered, and when
the signal has advanced to `processing_status = 'geocoded'`.

## Why this is a sub-project of its own

The umbrella architecture lists Sub-project D as story clustering, event
matching, and dual scoring, and shows geocoding in the pipeline without
assigning it. Sub-project C's design lists geocoding first among the things it
excludes. Neither document gives it an owner.

It is split out here, ahead of clustering, for two reasons. It is an independent
subsystem with its own reference data, its own failure modes, and no dependency
on anything clustering decides. And clustering needs coordinates as an input, so
building them in the same cycle would mean designing the consumer before the
producer exists.

The remainder of Sub-project D — story clustering, event matching, and the two
scores — is designed separately as D2 and consumes this sub-project's output
through the `signal_locations` table.

## Out of scope

Explicitly excluded, each its own later sub-project:

- story clustering, event matching, and event creation (D2);
- `early_signal_score` and `evidence_score` (D2);
- writing `events`, `event_signals`, `event_observations`, or `event_locations`;
- the Signal Radar API and its map UI (E).

Nothing here writes `verification_status`. Nothing here creates a row in
`diseases` or `pathogens`. Nothing here modifies `signals.ai_extraction`: the
extraction is the model's answer, and this sub-project records its own answer
beside it rather than editing it.

## Network posture

This sub-project makes no network requests at all.

The gazetteer is a GeoNames extract committed to the repository and seeded into
PostgreSQL, so a clone can migrate, seed, and geocode with no key, no account,
and no socket. That is the same contract `filter_rules.json` and
`ai_models.json` already have, and it means every test in this sub-project
exercises the real resolution path rather than a recorded fixture.

The cost is a seed artifact of a few megabytes and a coverage ceiling: a
gazetteer of this size contains provinces, districts, and towns down to roughly
a thousand inhabitants, and does not contain villages. That ceiling is stated
rather than hidden — a name below it resolves to a district or province
centroid, or to nothing, and says which.

Adding a network geocoder later is an adapter module and a precision rung, not a
change to the resolution policy.

## The three errors and their asymmetry

**Placing an outbreak in the wrong country is the worst error.** A coordinate
enters the database indistinguishable from a correct one, propagates into
clustering and event matching in D2, and puts a marker on a map for a country
that has no outbreak. Nothing downstream can detect it, because a coordinate
carries no evidence of how it was chosen. Niger matched to Nigeria is this error.

**Placing an outbreak too coarsely is a mild error.** A province centroid where
a town was meant is less useful but not false. It is visible as such, because
the row records the precision it achieved, and it degrades cleanly: D2 can weigh
a province-level match lower than a town-level one because it can see the
difference.

**Failing to place an outbreak at all is a recoverable error.** An unresolved
location costs a map marker. The row still exists, still names the place the
article named, and is still there to be resolved when the gazetteer grows or a
network provider is added.

The resolution policy follows directly from that ordering: never tie-break,
always coarsen, and record what actually happened.

## The resolution ladder

Every extracted location runs this ladder exactly once.

**Name forms.** Each name normalizes two ways. The `normalized` form is
casefolded, has runs of whitespace collapsed, and has punctuation stripped. The
`ascii` form additionally folds diacritics. Both forms are stored on every
gazetteer row and indexed. Forms are tried in order and their results are never
merged: an exact match must not be diluted by the collisions that folding
introduces.

**The steps.**

1. Resolve the extraction's `country` text to an ISO-3166 alpha-2 code through
   the country alias seed.
2. If no country was extracted, or none resolved, try the place name against the
   whole gazetteer, using the same form order as step 5 and ignoring the
   extraction's `admin1` text, which cannot be scoped without a country. If
   exactly one row worldwide matches, accept it. If more than one does, or none
   does, the location is unresolved at precision `unresolved`. Kinshasa survives
   this step; Springfield does not, and that asymmetry is the point.
3. With a country code, scope candidates to that country.
4. Resolve the extraction's `admin1` text to an admin1 code within that country.
   If it resolves, narrow candidates to that admin1.
5. Match `place_name` within the surviving scope: exact `normalized` form first,
   then `ascii` form, then alternate name. Admin2 rows are candidates alongside
   populated places, because reporting names districts as often as it names towns.
6. If exactly one candidate survives, accept it at that row's precision.
7. If several survive, or none does, coarsen: emit the admin1 centroid if admin1
   resolved, otherwise the country centroid.

Precision is ordered `place`, `admin2`, `admin1`, `country`, `unresolved`.

**Never tie-break.** No step chooses among surviving candidates by population,
by feature class, or by any other property. A province centroid is a less
precise true statement; the most populous Springfield is a guess wearing a
coordinate. This is the single rule the sub-project exists to enforce, and it
lives in a pure function so that a test can pin it down exactly.

## Confidence

`geocoding_confidence` is derived from how the match was made, never invented
and never taken from a model. The mapping is a table of named constants:

| Outcome | Confidence |
| --- | --- |
| place, exact `normalized` name | 0.95 |
| place, matched via `ascii` fold | 0.85 |
| place, matched via alternate name | 0.75 |
| admin2 | 0.70 |
| admin1 centroid | 0.55 |
| country centroid | 0.30 |
| unresolved | `NULL` |

Unresolved is `NULL`, not `0`. A zero would claim the system assessed the
location and found it worthless; a null says it has no assessment to offer.
Latitude, longitude, and geometry are `NULL` on the same rows for the same
reason.

## Provenance, and a gap inherited from Sub-project C

Every stored number in Sub-project C carries a `source_span` checked against the
article text. Places do not: `ExtractedLocation` carries `role`, `country`,
`admin1`, and `place_name`, and no span. Location grounding was never built.

This sub-project does not reopen that. It records the provenance it actually
has, which is the extraction's own strings kept verbatim beside the resolution:

- `place_name`, `admin1_name`, and `country_name` hold what the extraction said,
  unmodified;
- `resolved_name`, `geonames_id`, `country_code`, `admin1`, `admin2`,
  `latitude`, `longitude`, `geometry`, and `precision` hold what the gazetteer
  answered;
- `geocoding_source` holds `geonames-<dump-date>`, so a coordinate is traceable
  to the reference data that produced it.

A coarsened row is therefore never mistakable for a place-level hit, and "why
this coordinate" is answerable from the single row.

**Follow-up, not part of this sub-project:** adding `source_span` to
`ExtractedLocation` would make places as grounded as counts. It requires a
schema change in Sub-project C and re-extraction of every signal already
processed, which is why it is recorded here rather than done here.

## Architecture

```text
packages/backend/src/episignal_backend/geocode/
  documents.py    contracts: ExtractedPlace, Candidate, Resolution, ResolvedLocation
  normalize.py    pure: name forms, country alias lookup
  resolve.py      pure: the ladder, coarsening, confidence
  protocol.py     GazetteerRepository and GeocodeRepository boundaries
  repository.py   the only module importing SQLAlchemy
  locate.py       run_geocoding, orchestrating protocols only
geocode_runner.py  CLI entry point, wired to `corepack pnpm geocode:signals`
```

The seam discipline is Sub-project C's, unchanged. `documents.py`,
`normalize.py`, `resolve.py`, `protocol.py`, and `locate.py` import neither
SQLAlchemy nor httpx. `repository.py` is the only module that touches the
database. No module imports httpx, because nothing here uses the network.

`GazetteerRepository` answers four questions and nothing else: candidates for a
name within a scope, candidates for a name worldwide, the admin1 code for a name
within a country, and the centroid for a given admin1 or country. Keeping it
that narrow is what lets `resolve.py` be tested with tuples.

## Data model

**`gazetteer_places`** — seeded reference data, never written by a pass.

| Column | Notes |
| --- | --- |
| `geonames_id` | integer, primary key, stable across dumps |
| `name` | the GeoNames name, as published |
| `normalized_name` | casefolded, punctuation stripped, indexed |
| `ascii_name` | additionally diacritic-folded, indexed |
| `alternate_names` | text array, normalized, GIN-indexed |
| `feature_code` | `PCLI`, `ADM1`, `ADM2`, or a populated-place code |
| `precision` | `country`, `admin1`, `admin2`, or `place` |
| `country_code` | ISO-3166 alpha-2 |
| `admin1_code`, `admin2_code` | GeoNames administrative codes |
| `latitude`, `longitude`, `geometry` | PostGIS point, GIST-indexed |
| `population` | stored but never used to break a tie; kept for D2 to weigh |

Composite index on `(country_code, admin1_code, normalized_name)`, which is the
shape of the scoped lookup.

**`signal_locations`** — one row per extracted location, written by the pass.

Mirrors `event_locations` where the columns mean the same thing — `location_role`,
`country_code`, `admin1`, `admin2`, `place_name`, `latitude`, `longitude`,
`geometry`, `geocoding_source`, `geocoding_confidence` — and adds `signal_id`,
`precision`, `resolved_name`, `geonames_id`, `admin1_name`, and `country_name`.

`geometry` is GIST-indexed, because D2 matches on proximity and will query it
spatially.

Rows are replaced wholesale per signal rather than upserted per location: the
extraction is the sole input, so a re-run deletes the signal's rows and writes
the current answer inside one transaction. There is no partial state to
reconcile.

## The pass

`corepack pnpm geocode:signals` selects signals at `processing_status =
'extracted'` whose `ai_extraction` is present, in batches, oldest first.

For each signal it runs the ladder over every location in the extraction, writes
the resulting rows, and advances the signal to `geocoded`.

**A signal whose locations all fail to resolve still advances.** Absence of a
coordinate is not a processing failure, and sending it to `needs_review` would
fill the review queue with signals about places no gazetteer of this size will
ever contain. **A signal whose extraction names no locations at all also
advances**, with no rows written.

**A signal is never sent to `needs_review` by this pass.** The only failures
available to it are a missing gazetteer, which is an operator error that should
stop the run rather than mark signals, and a malformed stored extraction, which
is a bug in Sub-project C that should surface as one.

## Gazetteer updates

`geocoding_source` records the dump a coordinate came from. When the seed
artifact is replaced, previously geocoded signals keep coordinates attributed to
the older dump, which remains a true statement about how they were produced.

`corepack pnpm geocode:signals --stale` selects signals at `geocoded` whose
`signal_locations` rows carry a `geocoding_source` other than the current one,
and re-runs them. Without it a gazetteer update would reach only signals
processed after it, which makes the update mostly pointless; with it, the
backfill is one command and the row history says what changed.

## Seeding

`scripts/build_gazetteer.py` takes the raw GeoNames downloads — `countryInfo.txt`,
`admin1CodesASCII.txt`, `admin2Codes.txt`, and `cities1000.txt` — and emits a
single normalized `database/seeds/gazetteer_places.tsv.gz`. The artifact is
committed; the script is committed beside it so the artifact is reproducible and
its provenance is auditable.

**Where a centroid comes from.** None of those four files publishes a coordinate
for a country or an administrative unit, and the available substitutes are all
worse: a capital is not the centre of its country, and an arbitrary seat is not
the centre of its district. A unit's centroid is therefore the mean of the
places `cities1000` puts inside it. That point is at least inside the unit, and
it is deterministic, which matters because the artifact is committed and a
rebuild must not surface as a diff of noise.

A unit containing no place from `cities1000` is **dropped from the gazetteer**
rather than written at latitude 0, longitude 0. Null island sits in the Gulf of
Guinea, which is both a real place and a plausible one for an outbreak, so that
error would be invisible on a map. A dropped unit simply has no centroid to
coarsen into, and the ladder falls through to the next rung, which is the
behaviour it already has for any centroid it cannot find.

`database/seeds/country_aliases.json` maps country names to ISO-3166 alpha-2
codes, in the same reviewable shape `filter_rules.json` uses. It covers the
short forms, historical names, and common model spellings that `countryInfo.txt`
alone does not. Matching is exact against the `normalized` form and never fuzzy:
a country that fails to resolve is a seed row someone adds, not a deployment,
and never a silent near-miss.

The seed loader streams the gzipped file and upserts in batches keyed on
`geonames_id`, computing `geometry` from latitude and longitude. It extends the
existing `seeds.py` and `seed_runner.py` rather than introducing a second
seeding mechanism.

**Attribution.** GeoNames data is licensed CC BY 4.0. The attribution lives in
`database/seeds/gazetteer/ATTRIBUTION.md` and is referenced from `README.md`.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `EPISIGNAL_GEOCODE_BATCH_SIZE` | 200 | signals selected per pass |
| `EPISIGNAL_GEOCODE_MAX_SIGNALS_PER_RUN` | 2000 | bounds a single invocation |

No key, no rate limit, and no cost cap, because there is no provider to limit.

## Testing

Every test in this sub-project runs with no network and no database, except the
single live verification task.

- `normalize.py` and `resolve.py` are tested as pure functions over tuples,
  including each rung of the ladder, each coarsening path, and each confidence
  constant.
- The tie-break prohibition gets its own tests: two equally plausible candidates
  in the same admin1 must coarsen, and must not return either candidate,
  regardless of population.
- `locate.py` is tested against in-memory fakes of both protocols.
- `repository.py` is tested against a fake `Session` that records the statements
  it was handed, the same pattern `test_ai_repository.py` already uses. No live
  database is involved.
- Fixtures cover the named hard cases: Springfield with no country, Kinshasa with
  no country, Niger against Nigeria, a diacritic name matched by fold, a district
  name that exists only at admin2, and a village absent from the gazetteer.

## Acceptance criteria

1. A signal at `extracted` with a resolvable town name gains one
   `signal_locations` row at `place` precision and advances to `geocoded`.
2. A signal naming an ambiguous town within a resolved admin1 gains a row at
   `admin1` precision, with the extraction's `place_name` preserved verbatim and
   `resolved_name` naming the admin1.
3. A signal naming a place absent from the gazetteer, with no resolvable admin1,
   gains a row at `country` precision.
4. A signal naming a place that resolves to nothing gains a row with `precision`
   of `unresolved` and `NULL` latitude, longitude, geometry, and confidence.
5. A signal whose extraction names no locations advances to `geocoded` with no
   rows written.
6. No signal is sent to `needs_review` by this pass.
7. No candidate is ever selected by population, feature class, or any tie-break.
8. `signals.ai_extraction` is byte-identical before and after the pass.
9. Re-running the pass on a signal replaces its rows and leaves the same result.
10. `--stale` selects only signals whose rows carry a superseded
    `geocoding_source`.
11. `grep` finds no import of SQLAlchemy outside `geocode/repository.py`, and no
    import of httpx anywhere in `geocode/`.
12. The whole suite runs with no socket opened and no live database, apart from
    the live verification task.
13. `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`,
    `uv run mypy apps/api/src packages/backend/src`, and `corepack pnpm verify`
    all pass.
