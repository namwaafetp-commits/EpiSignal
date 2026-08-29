# Design — Pipeline Funnel v2: keyword gate, deferred retrieval, cluster extraction

**Date:** 2026-08-29
**Status:** approved by operator, planned
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
discover (title+url only) -> keyword gate -> retrieve body -> dedupe
  -> pre-group -> cluster extraction (one call per story) -> geocode -> match
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
`classify_title(title: str, keywords: KeywordRule) -> GateDecision`, where a
decision is `pass` (with the matched rule recorded) or `filter`.

- The keyword list is seed data, versioned like the disease vocabulary and
  seeded into a `keyword_rules` table: disease names, pathogen names, and
  context terms (`case`, `cases`, `death`, `deaths`, `outbreak`, `alert`,
  `quarantine`, `WHO`, `ministry of health`, `vaccin*`, `epidemic`,
  `suspected`, `confirmed`). Seeded, never hard-coded in the module, so the
  operator can widen it without a deploy.
- Matching is case-folded substring plus the existing GDELT rule keywords of
  the signal's query rule when known.
- When in doubt, the gate passes. A gate that silently eats a measles story
  with a vague headline costs more than an extra extraction. The list above is
  deliberately loose; tightening it is an operator decision made with data,
  not a default.

### D2 — Filtered is a status, never a deletion

`ProcessingStatus` gains `FILTERED = "filtered"`: terminal like `duplicate`,
it preserves the row with its title, url, and the matched rule recorded, and no
automated stage selects it. Dropping evidence silently contradicts the
provenance rule; a filtered row can be re-gated if the keyword list changes.
This adds one pg enum value: reversible migration, no data touched.

### D3 — Retrieval moves behind the gate

The GDELT connector stops fetching bodies at promotion. It stores the signal
at `fetched` with `raw_text = null`. A new gate+retrieval step between
dedupe-selection and extraction:

- gate rejects -> status `filtered`, done, no fetch;
- gate passes -> `ArticleFetcher` runs, then the existing normalization path
  (`normalized`); unfetchable -> the existing `retrieval_failed` review path,
  unchanged.

WHO/ECDC ingestion keeps fetching at ingest: those documents are official and
rare, and their pipeline is not where the cost lives.

### D4 — Pre-group becomes the story boundary

The built but disabled pre-group stage (`pregroup_enabled=false` since track O)
is turned on. Its `story_groups` / `story_group_members` tables, with
`representative` / `deferred` roles, already model exactly one thing: several
signals that are the same story. Membership stays deterministic (title
similarity within one rule group, one country, one time window) — grouping is
routing, never judgement.

### D5 — Cluster extraction: one call per story, grounded per member

Extraction schema version 3. One request carries up to four members of an open
story group (title plus up to ~4,000 characters of body each), each labelled
`source_index`. The model returns one extraction whose every count, span, and
transmission flag carries the `source_index` of the member it came from, plus
the usual five-slot brief and English title.

- The validator checks each `source_span` against the raw text of the member
  the claim cites — not against the concatenation. Provenance survives the
  batching; this is the invariant the whole design bends around.
- The accepted extraction is stored on the group's `representative` signal
  (schema v3 payload). Members are marked `duplicate` with
  `duplicate_of_signal_id` pointing at the representative — they leave the
  funnel exactly as content-duplicates do today, and the downstream stages
  (geocode, match, radar) see one signal per story with no changes.
- A rejected cluster call falls back to per-article extraction for that
  group's members under the current rules. Without this fallback, one bad
  article poisons the whole group's retry budget.
- `source_index` outside `0..n-1`, or a span not present in the cited member,
  is a rejection. Ungrounded is ungrounded even when batched.
- Disease second pass and cost ledger behaviour are unchanged; the cost row's
  `batch_size` records the cluster size.

### D6 — What does not change

Geocode ladder (gazetteer -> cache -> optional Nominatim -> country centroid),
event matching, the review queue and its typed causes, the radar read model,
the spend ledger, and the schedule chain order all stay as they are. The
chain's extract stage gains a gate+retrieve prefix and a pre-group lookup; it
does not grow new stages.

## Rejected alternatives

- **Embedding similarity for pre-grouping** — that is D2b's territory; the
  deterministic title grouping already built is enough to realize the savings.
- **Hardening the keyword list into code** — an operator-tunable seeded table
  keeps the recall lever in the operator's hands.
- **Storing the cluster extraction once per group in a new table** — rejected
  for now: it would ripple through the radar read model. The
  representative-carries-extraction design realizes the savings with zero
  read-model changes. Revisit only if per-member provenance display becomes a
  product need.

## Acceptance

- A live run with `pregroup_enabled=true` and the gate on: zero classification
  cost rows, extraction request count below the per-article baseline on a
  multi-source day, at least one cluster extraction accepted with valid
  per-claim provenance, and the fallback proven at least once (forced in a
  test even if live never triggers it).
- No signal is ever deleted. Filtered and duplicated rows remain queryable.
- `corepack pnpm verify` green, including regenerated contracts if any API
  shape moved (it should not).
