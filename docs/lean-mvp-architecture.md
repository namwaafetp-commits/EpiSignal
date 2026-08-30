# Lean MVP Architecture

The lean MVP reorients Phase 1 onto a one-VPS, global English-only,
event-centric surveillance product. This document supersedes the embedding
half of roadmap item `R` (BGE-M3 / pgvector story-group retrieval) and the
Gemini 2.5 Flash-Lite transition of issue #1. The committed direction is the
one this file records.

## Final architecture

```text
                    GDELT
              English-only queries
                       |
                       v
                raw candidates
                       |
                URL normalization
                       |
                       v
          exact / near-exact dedup
                 RapidFuzz
                       |
                       v
                  STORY GROUP
                       |
             representative article
                       |
                       v
            cheap AI classification
                Llama 3.1 8B
                       |
          irrelevant --+-- relevant
             stop             |
                              v
                     structured fields
                              |
                disease + country + time
                              |
                              v
                    recent event lookup
                              |
                      deterministic score
                              |
             +——-——————+———————+
             v                v               v
           match          ambiguous          new
             |             LLM judge          |
             +——-——————-——+———————+
                              v
                            EVENT
                              |
                              v
                       EVENT OBSERVATION
                              |
                     material change?
                       /             \
                     no               yes
                     |                 |
                    done            DeepSeek
                                       |
                                       v
                              update event summary
```

One app (FastAPI), one worker invocation (Python runners), one database
(PostgreSQL + PostGIS + pgvector scaffolding). No Kafka, Redis, Celery,
Elasticsearch, Kubernetes, or microservices. The chain is:

```
INGEST_WHO -> INGEST_ECDC -> DISCOVER -> RETRIEVE -> DEDUPE -> TRIAGE
  -> EMBED (scaffolding; not load-bearing) -> PREGROUP (default-off)
  -> EXTRACT -> GEOCODE -> MATCH -> SUMMARIZE
```

Every stage writes its own cost rows. `corepack pnpm verify` is the gate.

## Database schema

Core tables (trusted; not reintroduced):

* `sources` — `sources(id, name, source_type, base_url, feed_url, credibility_tier, is_official, active, created_at, updated_at)`
* `signals` — one retrieved document per row (`signals(id, source_id, url, canonical_url, title, normalized_title, raw_text, language, content_hash, published_at, retrieved_at, processing_status, triage_*, embedding, ai_extraction, first_seen_at, gdelt_seen_at, discovered_via, duplicate_of_signal_id, ...)`). Unique `(url, content_hash)`.
* `story_groups` / `story_group_members` — the pregroup stage's deterministic pre-groups of normalized signals keyed `(rule_group, country_code)` within a narrow temporal window.
* `events` — the core domain row:
  * `public_id uuid` + `slug` (unique, stable URLs)
  * `title` (auto-generated), `disease_id`, `pathogen_id`
  * `event_type` / `status` (`monitoring`/`ongoing`/`expanding`/`stable`/`declining`/`resolved`/`unknown`)
  * `verification_status` (`officially_confirmed` / `high_credibility` / `signal` / `unverified` / `rumor_monitoring`)
  * `country_code` / `admin1` / `admin2` + PostGIS geometry
  * `first_signal_at` / `event_start_date` / `last_updated_at`
  * `headline` / `summary` (the rendered, denormalized summary) — added `20260830_0019`
  * `article_count` / `last_summarized_at` — added `20260830_0019`
  * `early_signal_score` / `evidence_score` (dual 0–1 scores; verification status never derived from model confidence)
* `event_stats` — no separate table; scores live on `events`.
* `signal_locations` — resolved extraction sites keyed against the gazetteer (`signal_locations(id, signal_id, location_role, precision, country_code, admin1, admin2, place_name, latitude, longitude, geometry, geocoding_confidence, ...)`).
* `event_locations` — copies of `signal_locations` onto events.
* `event_locations` + `geocode_cache` + `gazetteer_places` — gazetteer resolution + cache.
* `ai_requests` — one cost row per model call (`ai_requests(id, ai_model_id, model_id, tier, purpose, signal_id, batch_size, prompt_tokens, completion_tokens, latency_ms, http_status, outcome, rejection_reason, prompt_price_per_million, completion_price_per_million, cost_usd, requested_at)`).
* `ai_models` — the roster (`ai_models(id, tier, model_id, label, provider, purpose, prompt_price_per_million, completion_price_per_million, active)`).

Lean-MVP addition (`20260830_0019`):

* `events.headline`, `events.summary`, `events.article_count`, `events.last_summarized_at`.
* `event_summaries(id, event_id, version, headline, summary, status, latest_development, uncertainties, model_id, source_signal_ids, counts, created_at)` with unique `(event_id, version)`. Every re-summary appends; the newest version is what `events.headline`/`summary` denormalize.

Scores on the lean-MVP table:

* `event_summaries.counts` — the snapshot the summary was written against (`{data_as_of, confirmed_cases, total_cases, deaths, ...}`), so material-change detection compares like with like.

What `events.last_summarized_at` makes cheap:

* The summary history is never diffed textually. The material-change detector compares the latest observation counts against `event_summaries.counts` of the newest summary, the unsummarized-article count, and the wall-clock age. See below.

## Event-matching rules

The matching engine stays the deterministic scorer of the verified build, not a model.

* Candidates are filtered before any score is computed:
  * same `disease_id` — different disease is an immediate zero/blackhole (`DISEASE_MISMATCH`)
  * compatible geography at the coarsest shared precision (`spatially_compatible`, `distance_km` + same-country/-admin1 guards)
  * both known `admin1` but equal-checked is a strong negative (strong negative/usually separate; implemented as a deterministic rejection `CONFLICTING_ADMIN1`)
  * temporal overlap within both the cluster window (`cluster_window_days`) and the candidate recency (`match_recency_days`)
* The score components (`events/score.py`, each 0–1) are weighted:
  * `disease` (0.30 in the verified code — must match exactly)
  * `spatial` (0.35, at coarsest shared precision: PLACE 1.0→0.5, ADMIN2 0.75, ADMIN1 0.50, COUNTRY 0.25)
  * `temporal` (0.20, recency-overlap in days, `max(0, 1 - gap/recency_days)`)
  * `precision` (0.15, `precision_weight` of the cluster's best primary location)
  * embedding `similarity` as an additive term (`SIMILARITY_WEIGHT = 0.15`) remains in `decide` — it can only add to, never veto, a deterministic score.
* `decide(cluster, candidates, *, threshold=0.70, review_threshold=None)` with an optional deterministic review band:
  * `score >= auto_threshold` → qualifies (existing threshold)
  * `[review_threshold, auto_threshold)` → ambiguous (when the band is configured): exactly one such candidate → `AMBIGUOUS`
  * `score < review_threshold` or no candidate → `CREATE`
  * 2+ qualifiers → `REFUSE` → `needs_review` via the review queue (existing verified behavior; human as escape hatch)
* Configurable bounds (all on a 0–1 scale; the plan describes 75/55 on a 0–100 scale):
  * `event_match_threshold` (auto) — default 0.60; operator sets 0.75 when the plan's 75 is wanted.
  * `event_match_review_threshold` — default 0.55 (the plan's 55).
  * `event_match_recency_days` / `event_match_distance_km` / `event_lookback_days` / `event_candidate_limit` / `event_followup_window_days` — as in the verified code. The plan's `EVENT_MATCH_LOOKBACK_DAYS=10` maps to `event_lookback_days=10` here.
* `events/judge.py` runs only on the ambiguous band, via the cheap classifier rung (Llama `purpose=triage`) unless benchmarking proves otherwise. Output `{same_event, confidence, reason}`. The `assemble` stage then attaches on `same_event: true`, and prefers a new event on any other outcome (false merge is worse than a duplicate event). Every judged candidate is costed with purpose `event_match_judge`.

The four calibration scenarios remain pinned (phuket stays separate from chiang mai; measles stays separate from dengue; three chiang mai follow-ups become one event). Thresholds that break calibration are wrong.

## AI model roles

Model selection is a reviewed roster fact, not code. Roster rows live in `ai_models` seeded by `load_ai_models()`. The chain resolves a `Ladder` from the active rows:

| Call site | Resolver | Purpose | Models tried |
| --- | --- | --- | --- |
| triage (cheap classify) | `run_triage` | `triage` | `meta-llama/llama-3.1-8b-instruct` (purpose=triage) |
| event match judge | `configure_judge` | `triage`-scoped if present, else tier-1 rung | Llama's ladder (one request per ambiguous candidate) |
| extraction / cluster extraction | `run_extraction` | none (general ladder) pass from `EXTRACTION_MIN_TIER = 2` | Gemini ladder tiers 2–3; tier 1 deliberately skipped for extraction |
| follow-up delta | `configure_delta` | lowest general tier 1 rung | tier-1 Gemini |
| event summarization | `configure_summary` | `event_summary` | `deepseek/deepseek-v4-flash-0731` (purpose=event_summary) |

Gemini vs Llama + DeepSeek (issue #1):

* The MVP direction is Llama = cheap classifier + judge, DeepSeek = event summarizer. This matches the operator's Gemini 2.5 transition supersession note (roster commit `02c23a7`). The provider implementation stays configurable: adding a rung (`ai_models` row) or a purpose flag is sufficient; no pass changes.
* OpenRouter (`openrouter_api_key`) and native Gemini (`gemini_api_key`) remain supported. The model-ledger is still the roster `cost_usd` computed from the ladder's prices, not from a provider-reported cost, so trailing spend is portable.

## Processing statuses

Statuses are a `CHECK` constraint, not a pg enum (recreate, not `ALTER TYPE`). The verified constraint now holds (incl. the `dismissed` and `filtered` vocabularies):

`fetched` → `normalized` → `classified` → `extracted` → `geocoded` → `matched` → terminal

Terminal-like `duplicate`, `failed`, `needs_review`, `filtered`, `dismissed` are closed to every stage's selector. A row never moves backward; `triage_status` and the `processing_status` CHECK are two orthogonal facts (status is idempotent — rerunning a stage that already selected a row advances it only once).

Event summarization adds no new `processing_status` value: it is keyed off `events.last_summarized_at` and the `event_summaries` history table, so rerunning the summarizer is idempotent by construction (an event whose counts did not change, with fewer than `resummary_new_article_count` unsummarized attachments, and younger than `resummary_max_age_hours`, keeps its current version).

## Retry / idempotency behavior

The DAILY chain runs under an advisory lock and advances each stage independently (a stage that raised does not roll back a stage that succeeded):

1. `run_ingestion` — `(url, content_hash)` unique constraint: a duplicate document is a counted `skipped`, never an insert.
2. `run_discovery` / `run_retry` — GDELT sightings are idempotent by `canonical_url` and a per-rule reach; the `published_at_offset_minutes` + retry attempts are finite.
3. `run_retrieval` — `stubs_awaiting_retrieval` now excludes `needs_review`; every failed retrieval opens a `RETRIEVAL_FAILED` review case (typed, not an inferred `needs_review`).
4. `run_dedupe` — `content_hash` equality, Jaccard title similarity as a gate, body shingle Jaccard on the normalized bodies — and, since `20260830_0019`, an additional RapidFuzz near-exact title rule (`stage0_near_exact_title_similarity >= 0.92` within `stage0_near_exact_window_hours = 48`) that catches syndicated copies without depending on body extraction having succeeded. A `duplicate_of_signal_id` always points to the flattened terminal primary; `primary_of` chains are resolved to depth one at write time and are never recursed at read time.
5. `run_triage` / `run_extraction` / `run_embedding` — all costed, climbing the relevant ladder rung(s) with `RunBudget(max_requests, max_cost_usd)` guards and a one-repair pass on triage/extraction rejection.
6. `run_geocoding` — local gazetteer first, Nominatim only when `nominatim_enabled` and cached on success.
7. `run_event_assembly` — clustering, candidate retrieval with `candidate_lookback_days` + `candidate_limit` + `ST_DWithin`, score + hard guard (disease mismatch, conflicting admin1, far/too-old time window), optional `AMBIGUOUS` → judge, then `finalize_event_creation`/`finalize_event_link`, then a per-event score apply (early_signal, evidence, verification status). Every decision is logged (`event match candidate event_id=... similarity=... score=... reason=...`; `matched event ...`; `judged event ... same_event=...`). `open_review(event_match_ambiguous, candidate_scores=...)` snapshots the deciding scores for the queue.
8. `run_summarization` — the summarize runner selects events whose `last_summarized_at` is null, behind `last_updated_at`, or older than `resummary_max_age_hours`, calls `should_resummarize(...)` (counts mismatch, 3+ unsummarized supporting articles, 24h wall-clock age), then, when the DeepSeek wiring exists, asks for a new `{headline, summary, status, latest_development, uncertainties}`. An accepted answer appends a versioned row to `event_summaries` and bumps `events.article_count`/`last_summarized_at`; the history is never overwritten.

No transition silently replaces an earlier value. Event observations are additive rows (`event_observations` has no upsert on the case/death columns), and contradicting numbers live as contemporaneous rows.

## Cost telemetry

`ai_requests` is the cost ledger. Every request — answered, rejected, or unavailable — is written there, with the price that was in force at the moment of the call copied onto the row (the roster can change without rewriting history). Rows costed by:

* `ai/triage.py` → purpose `triage`, `signal_id` set
* `ai/extract.py` (single + cluster + backfill + delta) → `extraction` / `follow_up`
* `events/judge.py` → `event_match_judge` (new `20260830_0019` purpose; the judge costs one request per ambiguous candidate)
* `events/summarize.py` → `event_summary` (one request per summarized event)

Aggregations:

* `ai/spend.py::trailing_spend(window_days)` → `SpendSummary(window_days, since, requests, signals, cost_usd, breakdown)` grouped by `(model_id, purpose, outcome)`.
* `spend_runner.py` (`pnpm spend:report`) prints 30-day trailing cost plus the per-purpose breakdown.

`ai_requests` is append-only; no downgrade discards rows. The ledger belongs to the operator's budget question (``$0.30 lifetime at the funnel v2 proof``, ~``$0.12 in 30 days at subproject O``) rather than to a model.

## Known limitations

* No multilingual ingestion: the GDELT query library is pinned to `language = English` (query rules hold the language; flipping one configuration value brings multilingual, not a code change — deliberately deferred to Phase 2).
* No BGE-M3 / pgvector retrieval: the lean MVP does not run semantic story-group search. The `embed` stage still exists in the chain to avoid a destructive migration but its output is not load-bearing for matching (matching similarity is at most an additive term; the ambiguous band is decided by the judge, not by an embedding). A future Phase 2 embedding would reintroduce a purpose-scoped `local` provider behind the existing `EmbeddingProvider` seam without touching matching invariants.
* No natural-language search: event retrieval is keyword plus structured filters (disease, country, admin1, status, verification_status, date window). `/search` on natural language is a separate, sequenced item (`G`/`J`).
* No personalized alerts, subscriptions, mobile app, forecasting, AI chat, or risk scoring. Those are itemized as non-goals in the operator's brief and are deliberately omitted.
* No Elasticsearch/OpenSearch. No Kafka. No Celery/RQ. No Kubernetes. The product runs on one 2–4 vCPU / 4–8 GB RAM VPS.
