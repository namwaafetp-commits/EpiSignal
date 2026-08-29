# Design — Pipeline Funnel v2: keyword gate, deferred retrieval, cluster extraction

**Date:** 2026-08-29
**Status:** approved by operator, corrected against the code on 2026-08-29, planned
**Author:** planner, from the operator's funnel proposal of 2026-08-29

## Problem

The daily chain still pays AI and fetch costs for articles that are not worth
them. Specifically:

1. Relevance is decided by a model call, when the discovery layer found the
   article through keywords in the first place.
2. Article bodies are downloaded for every promoted discovery result before
   any gate runs, including articles that will never pass.
3. Extraction runs per article, so a story reported by four outlets costs four
   extraction requests and yields one arbitrarily chosen answer.

## Outcome

A funnel that spends attention in the order evidence deserves it:

```
discover (title + url only)
  -> keyword gate -> retrieve body           [stage: retrieve]
  -> dedupe                                  [stage: dedupe]
  -> pre-group                               [stage: pregroup]
  -> cluster extraction, one call per story  [stage: extract]
  -> geocode -> match
```

Measured goals against the state after the 2026-08-29 optimizations
(title-only classification, tier-2 extraction floor, 8 workers):

- zero model requests for relevance classification;
- ~40-60% fewer extraction requests on multi-source days, because a story
  cluster is extracted once, not once per member;
- bodies fetched only for articles that pass the gate;
- wall clock roughly 2x faster per run, dominated by distinct-story count.

## Decisions

### D1 — Keyword gate replaces the AI relevance pass

`ingestion/keyword_gate.py` holds one pure function:

```python
def classify_title(title: str, rules: Sequence[FilterRule]) -> GateDecision
```

A `GateDecision` is `passed=True` with the rule that matched, or `passed=False`
with no rule — a rejection is the absence of every rule, so there is nothing to
attribute it to.

- **Storage reuses `filter_rules`.** `FilterRuleGroup` gains
  `TITLE_INCLUSION = "title_inclusion"`, alongside the existing
  `title_exclusion` and `domain_blocklist` groups. The rules seed into
  `database/seeds/filter_rules.json` through the loader that already exists.
  No new table, no new model, no new seed file, no migration for the rule
  store: one table and one seed file remain the operator's whole surface for
  tuning what the funnel keeps.
- **The disease vocabulary is not copied into the seed.** The gate's rule set
  is the union of the active `title_inclusion` rows and one synthetic rule per
  `diseases.canonical_name` and per synonym. The reviewed vocabulary stays the
  single source of disease identity; the seed carries only what the vocabulary
  does not: pathogen and context terms (`outbreak`, `cases`, `deaths`,
  `quarantine`, `ministry of health`, `vaccination`, `epidemic`, `suspected`,
  `confirmed`, and the rest of the list in the plan's Task 1).
- **Matching is case-folded substring** against the title, on whitespace-
  collapsed text. Not a regular expression: the `title_exclusion` group holds
  patterns because rejection has to be precise, while inclusion has to be
  generous. A keyword shorter than four characters is a seeding error, because
  a substring that short matches words nobody meant.
- **When in doubt, the gate passes.** No active `title_inclusion` rules means
  every title passes; the gate can never be the reason a run stores nothing.
  A gate that silently eats a measles story with a vague headline costs more
  than an extra extraction. Tightening the list is an operator decision made
  with data, not a default.

### D2 — Filtered is a status, never a deletion

`ProcessingStatus` gains `FILTERED = "filtered"`: terminal like `duplicate`,
it preserves the row with its title and url, and no automated stage selects
it. Dropping evidence silently contradicts the provenance rule; a filtered row
can be re-gated by setting it back to `fetched` if the keyword list widens.

`processing_status` is **not** a PostgreSQL enum. `db/types.vocabulary()`
builds `sa.Enum(..., native_enum=False, create_constraint=True)`, so the value
set is a `VARCHAR` plus the `processing_status_values` CHECK constraint. The
migration drops and recreates that constraint, exactly as
`20260829_0014_manual_review_cases` did for `dismissed`. `ALTER TYPE ... ADD
VALUE` would fail.

No column records which rule filtered a row, because a filtered row is one that
no rule matched. Provenance is the title, which is stored, plus the rule set,
which is versioned in git.

### D3 — Retrieval moves behind the gate, into its own stage

The GDELT connector stops fetching bodies at discovery. `run_discovery` calls
a new `connector.defer(...)`, which stores the sighting at `fetched` with
`raw_text = null`. A new `retrieve` stage sits between `discover` and `dedupe`:

- gate rejects -> status `filtered`, done, no fetch;
- gate passes -> `ArticleFetcher` runs and the existing
  `DiscoveryRepository.promote` writes the body, the recomputed content hash,
  and the incremented attempt counter;
- unfetchable -> `record_failed_attempt`, which is the existing
  `retrieval_failed` review path once the attempt budget is spent. Unchanged.

WHO/ECDC ingestion keeps fetching at ingest: those documents are official and
rare, and their pipeline is not where the cost lives.

**Two selection queries have to change or this decision silently fails:**

1. `SqlAlchemyDedupeRepository.pending` selects `fetched AND raw_text IS NOT
   NULL`, and `mark_normalized` is the only writer of `normalized`. Retrieval
   must therefore complete *before* the dedupe stage, which is why `retrieve`
   is a stage and not a prefix inside `extract`.
2. `SqlAlchemyDiscoveryRepository.stubs_awaiting_retrieval` selects any GDELT
   signal with `raw_text IS NULL` and no status filter at all. Left alone, the
   discover stage's retry pass would fetch every gate-passed signal before the
   gate ran, and would re-fetch every `filtered` signal forever. It gains
   `processing_status == needs_review`, which is the population it was always
   meant to serve.

### D4 — Pre-group becomes the story boundary, and a stage

The built but disabled pre-group stage (`pregroup_enabled=false` since track O)
is turned on and joins the chain between `dedupe` and `extract`. Its
`story_groups` / `story_group_members` tables, with `representative` /
`deferred` roles, already model exactly one thing: several signals that are the
same story. Membership stays deterministic (rule group + country + day window)
— grouping is routing, never judgement.

`pregroup_enabled` is also this item's rollback lever. Set it false and no
groups are written, so cluster extraction has nothing to select and every
signal takes the per-article path that exists today. No new configuration flag
is introduced by this item.

**The deferral exclusion has to move.** `~_deferred_by_open_group()` is applied
in `awaiting_classification` only. Once the relevance pass leaves the chain,
`awaiting_extraction` becomes the selection that must honour it, or every
deferred member is extracted individually and the entire saving evaporates.

### D5 — Cluster extraction: one call per story, grounded per member

Extraction schema version 3. One request carries up to four members of an open
story group (title plus up to 4,000 characters of body each), each labelled
`source_index`. The model returns one extraction whose every count and
transmission flag carries the `source_index` of the member it came from, plus
the usual five-slot brief and English title.

- **Per-article extraction becomes the one-member case.** `source_index`
  defaults to `0` on `GroundedCount` and `GroundedFlag`, and
  `check_grounding(extraction, bodies)` takes a sequence of member bodies. The
  single-article path passes `(raw_text,)`. One grounding implementation
  serves both, so the batched path cannot drift from the checked path.
- The validator checks each `source_span` against the raw text of the member
  the claim cites — not against the concatenation. Provenance survives the
  batching; this is the invariant the whole design bends around.
- `source_index` outside `0..n-1`, or a span not present in the cited member,
  is a rejection. Ungrounded is ungrounded even when batched.
- The accepted extraction is stored on the group's `representative` signal.
  Members are marked `duplicate` with `duplicate_of_signal_id` pointing at the
  representative — they leave the funnel exactly as content-duplicates do
  today, and the downstream stages (geocode, match, radar) see one signal per
  story with no changes.
- A rejected cluster call falls back to per-article extraction for that
  group's members under the current rules. Without this fallback, one bad
  article poisons the whole group's retry budget.
- Disease second pass and cost ledger behaviour are unchanged; the cost row's
  `batch_size` records the cluster size and its `signal_id` the representative.
- **The backfill floor is pinned at 2.** `awaiting_backfill` selects rows below
  `EXTRACTION_SCHEMA_VERSION`; bumping that constant to 3 would make every
  stored v2 row a backfill candidate and re-extract the whole corpus on the
  next run. A v2 row is structurally a v3 row with `source_index = 0`, so a new
  `BACKFILL_MIN_SCHEMA_VERSION = 2` becomes the selection floor and the version
  constant is free to move.

### D6 — What does not change

Geocode ladder (gazetteer -> cache -> optional Nominatim -> country centroid),
event matching, the review queue and its typed causes, the radar read model,
the spend ledger, and the extraction ladder's tier-2 floor all stay as they
are.

The chain does grow two stages — `retrieve` and `pregroup` — because D3's
ordering requires it, and because `schedule/stages.py` deliberately gives each
stage its own session so a failing stage cannot roll back a succeeding one.
`StageName` is a `StrEnum` whose values are JSONB keys in
`pipeline_runs.stage_counts`, so adding stages needs no migration.

The AI relevance pass is unwired from the chain but is **not deleted**. Keeping
`run_classification` and `awaiting_classification` intact for one release makes
the rollback a one-line change in `stages.py`.

## Rejected alternatives

- **Embedding similarity for pre-grouping** — that is D2b's territory; the
  deterministic title grouping already built is enough to realize the savings.
- **A separate `keyword_rules` table** — `filter_rules` already carries a
  `rule_group` discriminator, an idempotent seed loader, a Pydantic seed model,
  and an admin-editable row shape. A second rule table would give the operator
  two places to look and this item four more files to write.
- **Copying disease names into the keyword seed** — the reviewed vocabulary is
  the single source of disease identity, and a copy drifts the first time a
  disease is added.
- **A `signals.filter_rule_id` column** — there is no rule to record on a
  rejection, since a rejection is the absence of every rule.
- **Keeping the gate inside the extract stage** — dedupe would never see a body
  and no signal would ever reach `normalized`.
- **A new `keyword_gate_enabled` flag** — `pregroup_enabled` already exists and
  already disables the expensive half of this item.
- **Storing the cluster extraction once per group in a new table** — rejected
  for now: it would ripple through the radar read model. The
  representative-carries-extraction design realizes the savings with zero
  read-model changes. Revisit only if per-member provenance display becomes a
  product need.

## Corrections to the approved design

Recorded so the worker does not re-derive them, and so the operator can see
exactly what moved between approval and planning. Each was found by reading the
code the decision touches.

| # | Approved | Corrected | Evidence |
| --- | --- | --- | --- |
| 1 | Gate rules live in a new `keyword_rules` table | Reuse `filter_rules` with a `title_inclusion` group | `models/discovery.py:30`, `seeds.py:64`, `ingestion/repository.py:150` |
| 2 | `filtered` "adds one pg enum value" | Drop and recreate the `processing_status_values` CHECK constraint | `db/types.py:209`, `20260829_0014_manual_review_cases.py:75` |
| 3 | The filtered row records the matched rule | A rejection has no matched rule; the title is the provenance | D1's own definition of a rejection |
| 4 | The chain does not grow new stages | `retrieve` and `pregroup` become stages | `ingestion/repository.py:341` — dedupe needs bodies |
| 5 | (unstated) | `stubs_awaiting_retrieval` needs a `needs_review` status filter | `ingestion/repository.py:247` |
| 6 | (unstated) | The deferral exclusion moves to `awaiting_extraction` | `ai/repository.py:115` vs `ai/repository.py:135` |
| 7 | (unstated) | Backfill selection pins to a floor of 2, not to the version constant | `ai/repository.py:161` |
| 8 | The gate also uses the signal's GDELT rule keywords | Dropped: the disease vocabulary already covers it | Adds plumbing for no measurable recall |

## Acceptance

- A live run with `pregroup_enabled=true` and the gate on: zero classification
  cost rows, extraction request count below the per-article baseline on a
  multi-source day, at least one cluster extraction accepted with valid
  per-claim provenance, and the fallback proven at least once (forced in a
  test even if live never triggers it).
- No signal is ever deleted. Filtered and duplicated rows remain queryable.
- The backfill queue does not grow when the schema version moves to 3.
- `corepack pnpm verify` green, including regenerated contracts if any API
  shape moved (it should not).
