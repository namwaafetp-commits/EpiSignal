# Design — Event-based surveillance: early metadata, embeddings, event summaries

**Date:** 2026-08-29
**Status:** approved by operator, planned
**Author:** planner, from the operator's event-based surveillance brief of 2026-08-29
**Roadmap item:** `R` — depends on `O2`. Absorbs the embedding half of `D2b`.

## Problem

The operator's brief describes a funnel this repository has largely built
already: normalization, exact and near-exact deduplication, cheap
classification, articles and events as separate entities, candidate blocking by
disease and geography and time, conservative matching, a cost ledger, a status
machine, and material-update detection all exist and are covered by 1,055
passing tests.

Three things in the brief do not exist, and one existing thing is weaker than
the brief requires.

1. **No embeddings.** There is no `pgvector` extension, no vector column, and
   no semantic similarity anywhere. Event matching is entirely deterministic:
   disease identity, haversine distance, and time windows. Two reports of one
   outbreak that share no vocabulary do not match.
2. **No event-level summary.** `events.ai_summary` is a declared column that
   nothing writes — the only references in the codebase are the model
   definition and the schema check. Readers see per-signal five-slot briefs;
   there is no narrative that describes the event rather than one article.
3. **No summary provenance history.** Nothing records which articles produced
   which version of an event's summary, so a summary that changes cannot be
   audited against the evidence that changed it.
4. **Blocking metadata arrives too late.** Disease and geography are produced
   by the extraction pass, which reads the full body at tier 2 or above, and by
   the geocoder that runs after it. Candidate blocking therefore cannot use the
   article's own disease and place until the most expensive stage has already
   run. The pre-group stage works around this with the query rule's group and
   the *publisher's* country, which is a proxy, not the article's geography.

## Outcome

```
discover (title + url)
  -> keyword gate            [O2, $0]
  -> retrieve body           [O2]
  -> normalized-title dedup  [new, $0, pre-fetch]
  -> exact/near dedup        [existing]
  -> Llama 3.1 8B triage     [new: relevance + disease + country + admin1 + event_type]
  -> multilingual MiniLM embedding   [new, local ONNX, 384d]
  -> pre-group / cluster extraction   [O2]
  -> candidate event blocking + embedding-assisted matching  [new]
  -> attach or create event
  -> material-update detection        [existing delta pass, extended]
  -> DeepSeek event summary + summary history   [new]
```

Measured goals:

- candidate blocking uses the article's own disease and admin1, produced for a
  few hundred tokens, instead of the publisher's country;
- two reports of one outbreak that share a disease, a place, and a week but not
  a vocabulary become one event;
- one event carries one narrative summary, regenerated only on a material
  update, traceable to the exact articles that produced it;
- no increase in false merges: every existing deterministic guard stays, and
  embedding similarity can only ever *add* a match, never override a conflict.

## Decisions

### E1 — The keyword gate and Llama triage are complementary, not competing

The operator's brief specifies `meta-llama/llama-3.1-8b-instruct` for
classification. `O2` replaces the previous AI relevance pass with a $0 keyword
gate. Both are kept, in this order:

- the **keyword gate** runs first, on the title alone, before any body is
  fetched. It costs nothing and is biased to pass. Its job is to stop obvious
  non-stories from ever costing a page fetch;
- the **Llama triage pass** runs after retrieval and deduplication, on title
  plus a snippet, and produces the structured blocking key the funnel actually
  needs: `relevant`, `public_health`, `category`, `event_type`, `disease`,
  `country`, `admin1`, `admin2`, `location_text`, `confidence`.

This is not the relevance pass `O2` removed. That pass answered one boolean for
a model's price. This one answers the six fields that let candidate blocking
happen before the expensive extraction, which is the reordering the whole brief
is built around. Relevance is a by-product.

An article the gate passed and Llama marks `relevant = false` becomes
`filtered`, the terminal status `O2` introduced. Nothing is deleted.

### E2 — Purpose-scoped model rosters

`ai_models` is tier-scoped but not purpose-scoped, so every pass climbs the same
ladder. Three models now serve three different jobs, and Llama must not answer
an extraction request.

`ai_models` gains a nullable `purpose` column. `NULL` means "any purpose",
which is what every existing row keeps, so no seeded row changes meaning.
`Ladder.build` gains a `purpose` argument and filters rows whose purpose is set
and does not match.

Seeded additions:

| Model | Purpose | Tier |
| --- | --- | --- |
| `meta-llama/llama-3.1-8b-instruct` | `triage` | 1 |
| `deepseek/deepseek-v4-flash-0731` | `event_summary` | 1 |

`AiPurpose` gains `TRIAGE` and `EVENT_SUMMARY`, so the existing cost ledger
separates their spend with no new table.

### E3 — Llama output is validated, repaired once, then abandoned

An 8B model's JSON is not reliable. The triage pass therefore:

- sends title, snippet, source name, published-at, url, and language;
- uses temperature 0 and OpenRouter structured output;
- validates against a Pydantic model where every field except `relevant` and
  `confidence` is nullable;
- on a validation failure, retries **once** with the validation error appended
  to the prompt — the repair attempt — and then gives up;
- writes a cost row for every attempt, answered or not, and on final failure
  leaves the signal selectable rather than dropping it. A failed triage is
  logged and counted, never silent.

`disease` is resolved against the reviewed vocabulary exactly as the extraction
pass already does; a name the vocabulary does not know is recorded as text and
resolves to no `disease_id`, rather than inventing one.

### E4 — Embeddings are local, batched, loaded once, and behind an abstraction

`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384
dimensions, generated locally through quantized ONNX by default.

**Operator lean correction (2026-08-30):** The first live BGE-M3 load was
stopped after several minutes without completing. Before model weights, its
Torch runtime had added about 728 MiB; the incomplete cache alone reached
1.14 GB. The replacement is the 50-language (including Thai) multilingual
MiniLM model that FastEmbed lists at about 0.22 GB. FastEmbed removes Torch and
uses ONNX Runtime. This preserves local multilingual embeddings and the
provider seam while materially reducing disk, download, startup, and memory
cost. See the [FastEmbed supported-model table](https://qdrant.github.io/fastembed/examples/Supported_Models/)
and the [model card](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2).

- `EmbeddingProvider` is a Protocol with one method,
  `embed(texts: Sequence[str]) -> Sequence[Sequence[float]]`. Clustering never
  imports a model library, so the provider can be swapped for a hosted one
  without touching matching logic.
- The local provider loads the model once at construction and is held for the
  life of the worker process. A provider constructed per article is a defect.
- Input text is `f"{title}\n{snippet}"`, snippet being the first 1,200
  characters of the body — the same excerpt constant the classification pass
  already uses.
- Vectors are L2-normalized at write time, so cosine similarity is an inner
  product and the index can use `vector_cosine_ops` honestly.
- Storage: `signals.embedding vector(384)`, nullable, with an HNSW index.
  Nullable because embedding is enrichment: a signal without one still matches
  deterministically, exactly as today.

Configuration:
`EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`,
`EMBEDDING_PROVIDER=local`.

`pgvector` is enabled by migration alongside the existing PostGIS extension.

### E5 — Embedding similarity may add a match; it may never override a conflict

This is the safety invariant the whole design bends around, and it is the
operator's own rule: a false merge hides a geographically distinct outbreak.

The existing `events/cluster.py` compatibility predicates — `compatible`,
`spatially_compatible`, `temporally_compatible` — stay exactly as they are and
run **first**. Embedding similarity is consulted only for pairs those
predicates already permit.

```
required, unchanged:   disease compatible
                       AND country compatible
                       AND time window compatible
                       AND NOT (both admin1 known AND different)

then, new:             cosine similarity >= EVENT_MATCH_THRESHOLD
                       contributes to match_score
```

Two consequences, both deliberate:

- A pair with conflicting `admin1` is refused **before** similarity is
  computed. Dengue in Chiang Mai and dengue in Phuket cannot merge no matter
  how similar their prose.
- A pair the deterministic rules already accept is not rejected for low
  similarity. Embeddings can only raise confidence, never veto — otherwise a
  terse official bulletin would be split from the reporting it confirms.

Ambiguous cases keep the existing behaviour: a review case, not a merge.

Thresholds, all configurable, all starting values rather than constants:

```
EVENT_LOOKBACK_DAYS=7
EVENT_CANDIDATE_LIMIT=20
NEAR_DUPLICATE_THRESHOLD=0.92
EVENT_MATCH_THRESHOLD=0.80
NOVEL_ARTICLE_SIMILARITY_THRESHOLD=0.88
RESUMMARY_NEW_ARTICLE_COUNT=3
RESUMMARY_MAX_AGE_HOURS=24
```

### E6 — Event summaries: DeepSeek, on material update only, with history

`events.ai_summary` stops being dead. A new `events/summarize.py` pass fills it
and the structured event fields, and writes an `event_summary_history` row for
every version.

Triggered when, and only when:

- the event was just created; or
- a new **official** source attached; or
- the newly attached article is semantically novel (cosine below
  `NOVEL_ARTICLE_SIMILARITY_THRESHOLD` against the articles used in the last
  summary); or
- `RESUMMARY_NEW_ARTICLE_COUNT` articles have attached since the last summary;
  or
- the last summary is older than `RESUMMARY_MAX_AGE_HOURS` **and** at least one
  article has attached since; or
- an operator forces it.

An event with no new evidence is never re-summarized. The last condition
carries the "and at least one article" clause deliberately: age alone is not
new information, and re-summarizing on a clock would spend money to produce the
same paragraph.

Representative selection, `select_representative_articles(event_id, max_articles=6)`,
prefers in order: an official source, then a primary report, then the most
recent, then one carrying new quantitative information, then the semantically
most novel. Near-identical syndicated copies are excluded by the similarity
that already marks them duplicates.

The summary model returns the brief's schema — headline, summary, disease,
event_type, geography, event_date, cases, deaths, hospitalized,
affected_population, official_confirmation, response_actions, risk_level,
uncertainties, latest_development, source_count — every epidemiological number
nullable, and conflicts preserved in `uncertainties` rather than resolved.

Numbers are cross-checked against `event_observations` before storage: a
summary claiming a case count no observation supports is a rejection, not a
correction. The existing grounding discipline applies to event summaries too.

### E7 — Retrofits to existing stages

Small, and each one closes a gap the brief names:

- **`signals.normalized_title`**, stored and indexed, plus a normalized-title
  dedup check that runs *before* retrieval. Today near-duplicate detection needs
  bodies, so syndicated copies are each fetched before being merged. Comparing
  normalized titles at the gate makes that free.
- **`signals.snippet`** is not added. The first 1,200 characters of `raw_text`
  already serve as the excerpt, and a stored copy would drift from its source.
- **`ai_requests.event_id`**, nullable, so "cost per event" is answerable. The
  ledger already carries `signal_id`.
- **`spend:report` aggregates**: cost today, cost this month, cost per 1,000
  candidate articles, cost per event, classification volume, summary volume.
- **Decision logging**: every match, every rejection with its reason
  (`conflicting_admin1`, `similarity_below_threshold`, `outside_time_window`),
  every event creation, and every re-summarization with its trigger.

### E8 — What does not change

Ingestion connectors, URL canonicalization, the content-hash fingerprint, the
existing dedupe pass, the geocode ladder, the review queue and its typed
causes, the radar read model, the scheduler's failure policy, and every
invariant in `O2`. `news_articles` is not created: `signals` is that table, and
a second one would split provenance across two schemas.

## Rejected alternatives

- **A parallel `news_articles` / greenfield pipeline** — two pipelines over one
  database, duplicated ingestion, and provenance split in half.
- **HDBSCAN/DBSCAN batch clustering** — the operator's brief rules it out for
  v1, and incremental matching is what a continuously arriving feed needs.
- **Embedding similarity as a veto** — would split an official bulletin from
  the reporting that confirms it.
- **Replacing the keyword gate with Llama** — the gate is free and runs before
  the fetch; Llama cannot, because it needs a snippet.
- **A separate `ai_usage` table** — `ai_requests` already carries model,
  tokens, cost, latency, outcome, purpose, and batch size. It needs one column.
- **Storing the snippet** — a denormalized copy of the first 1,200 characters
  of a column that already exists.
- **Re-summarizing on age alone** — spends money to reproduce a paragraph.

## Conflicts with the brief, resolved

Recorded so the worker does not relitigate them.

| # | Brief says | Resolved as | Why |
| --- | --- | --- | --- |
| 1 | Llama does classification | Llama does structured triage after the $0 gate | The gate is free and runs pre-fetch; Llama supplies the blocking key the gate cannot |
| 2 | Create `news_articles` | Use `signals` | It is that table; a second splits provenance |
| 3 | Create `ai_usage` | Add `event_id` to `ai_requests` | The ledger already has every other field |
| 4 | Store `snippet` | Derive from `raw_text[:1200]` | A stored copy drifts from its source |
| 5 | `event_summary_history` optional | Required | Surveillance auditability is not optional here |
| 6 | Re-summarize when summary is old | Old **and** new evidence exists | Age is not information |
| 7 | Embedding similarity decides matches | Deterministic guards decide; similarity adds confidence | A false merge hides an outbreak |

## Acceptance

- The four calibration fixtures resolve as specified: three Chiang Mai dengue
  reports become one event; Chiang Mai and Phuket dengue become two; dengue and
  measles in Chiang Mai become two; a Monday report and a Wednesday follow-up
  become one event with two articles and an updated summary.
- A live run produces at least one event summary with an
  `event_summary_history` row naming the exact articles used.
- `spend:report` answers cost today, cost this month, cost per 1,000 candidate
  articles, and cost per event.
- No signal is deleted at any stage; `filtered` and `duplicate` rows stay
  queryable.
- Re-running any worker creates no duplicate event and no duplicate summary.
- `corepack pnpm verify` green, contracts regenerated if any API shape moved.
