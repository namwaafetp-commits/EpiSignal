# Completion Report — Lean MVP Implementation

**Date:** 2026-08-30
**Branch:** `codex/event-surveillance`
**Verification:** `corepack pnpm verify` — exit 0
**Agent:** worker (muse-spark-1.2)

## Architecture implemented

```
GDELT (English-only) -> raw candidates -> URL normalization -> exact/near-exact dedup (RapidFuzz)
  -> triage (Llama 3.1 8B, title+snippet, no repair retry) -> structured fields (disease+country+time)
  -> recent event lookup (lookback+limit) -> deterministic score (disease/country/admin1/event_type/title)
     -> match (>= auto) / ambiguous (55-74 -> LLM judge) / new (< review)
       -> EVENT -> OBSERVATION (additive) -> material-change? -> DeepSeek summary -> API/UI
```

One app (FastAPI), one worker surface (runners + `schedule/stages.py` `DAILY_CHAIN`),
one database (PostgreSQL), one deployable unit on one VPS. Scheduler is `cron`
via `schedule/run.py` advisory lock; scheduler is not a separate service.

## Migrations added

| Revision | What |
| --- | --- |
| `20260830_0019_event_summaries` | `events.headline`, `events.summary`, `events.article_count`, `events.last_summarized_at`; `event_summaries(id, event_id, version, headline, summary, status, latest_development, uncertainties, model_id, source_signal_ids, counts, created_at)` with `(event_id, version)` unique; widens `ai_purpose_values` and `ai_model_purpose_values` to include `event_match_judge`. |

Downgrade refuses if cost rows with purpose `event_match_judge` exist.

## Files changed

See `git diff codex/event-surveillance` — 36 files, ~2400 insertions (the lean MVP delta;
the branch also carries the earlier R-plan embeddings/triage commits vs `main`).

Lean MVP touchpoints (delta vs head before this session's work):

* `packages/backend/src/episignal_backend/config.py` — `event_match_review_threshold`, `event_match_judge_batch_size`, `resummary_new_article_count`, `resummary_max_age_hours`, `summary_max_sources`, `stage0_near_exact_*`.
* `packages/backend/src/episignal_backend/ingestion/dedupe.py` + `rapidfuzz` dependency — `DedupeThresholds.near_exact_title / near_exact_window_hours` + `near_exact_title_match` (fuzz.ratio on raw title, exclusive of exact equality, requires `published_at` within window).
* `packages/backend/src/episignal_backend/events/documents.py` — `MatchAction.AMBIGUOUS`, `SummarySource`, `EventForSummary`; `SignalForMatching.title`, `CandidateEvent.title/recent_source_titles`.
* `packages/backend/src/episignal_backend/events/match.py` — `decide(..., review_threshold)`, `AMBIGUOUS` band.
* `packages/backend/src/episignal_backend/events/judge.py` — `EventMatchJudgement{same_event, confidence, reason}`, `run_judge` (temp 0.0, strict schema, one repair semantics), `JudgeWiring`, `configure_judge` (prefers `purpose=triage` Llama).
* `packages/backend/src/episignal_backend/events/summarize.py` — `EventSummaryVerdict{headline, summary, status, latest_development, uncertainties}`, `SummarySource`, `run_summary` (DeepSeek, purpose `event_summary`), `should_resummarize` (counts mismatch, 3+ unsummarized, 24h age), `pick_representative_sources` (official > quantitative > recency, deterministic).
* `packages/backend/src/episignal_backend/events/repository.py` — `signals_to_match` carries title; `candidate_events` carries event title + batched `recent_source_titles`; `record_observation` guards on `(event_id, signal_id)` for idempotency; `events_awaiting_summary` + `store_summary` (append version, denormalize onto `events`, bump `article_count`).
* `packages/backend/src/episignal_backend/events/assemble.py` — `review_threshold`, `judge_model/judge_spec` params; Δ-logged per-candidate scores; `AMBIGUOUS -> run_judge -> attach else new event (prefer new when uncertain)`; `cost_row` pulse written with `EVENT_MATCH_JUDGE`.
* `packages/backend/src/episignal_backend/events/protocol.py` — added `events_awaiting_summary` / `store_summary`.
* `packages/backend/src/episignal_backend/models/event.py` — `Event(headline, summary, article_count, last_summarized_at)`, `EventSummary` table.
* `packages/backend/src/episignal_backend/models/__init__.py`, `packages/backend/src/episignal_backend/db/types.py` (`EVENT_MATCH_JUDGE`).
* `packages/backend/src/episignal_backend/schedule/{chains,documents,stages}.py` — `StageName.SUMMARIZE` after `MATCH`, runner `_summarize` and judge wiring in `_match`, `build_stage_runners`.
* `packages/backend/src/episignal_backend/event_runner.py`, `dedupe_runner.py` — wired review threshold / near-exact thresholds from settings.
* `packages/backend/src/episignal_backend/summarize_runner.py` — `summarize:events` (limit, guard, `should_resummarize`, sorted pickup, cost rows purpose `event_summary`).
* `apps/api/src/episignal_api/{dependencies,factory}.py` — `get_session`, `get_event_page` (disease/country/admin1/status/verification_status/start_date/end_date), mounted `events` router.
* `apps/api/src/episignal_api/routes/events.py` — `GET /api/v1/events`, `GET /api/v1/events/{public_id}`, `GET .../sources`, `GET .../observations`; `GET /api/v1/events` is `keyword + structured filters` per plan.
* `packages/contracts/{openapi.json,src/index.d.ts}` — regenerated from `export_openapi.py` (openapi-typescript).
* `apps/web/src/lib/api-events.ts` — validated fetchers (`getEventList`, `getEventDetail`, `getEventSources`, `getEventObservations`), runtime response guards, `formatVerificationStatus`, `dateLabel`.
* `apps/web/src/app/events/page.tsx` — list with `disease/country/status` filters linking to `/events/{public_id}`.
* `apps/web/src/app/events/[publicId]/page.tsx` — one-page answers (headline/disease/place/status/verification, summary+latest_development+uncertainties, latest known counts, observation timeline, source traceability with publication datetime + URL).
* `apps/web/src/components/home-shell.tsx` — `Events` nav link.
* `packages/backend/tests/fixtures/lean_mvp/30_candidates.json` — 30 sightings exercising exact/near duplicates, follow-ups (42/68/91), distinct geographies, distinct diseases, irrelevant football fever, unknown-respiratory cluster.
* `package.json` — `summarize:events`, `test:pipeline`.
* `.env.example`, `apps/api/.env.example` — lean MVP knob placeholders.
* `docs/lean-mvp-architecture.md` — single authoritative MVP direction (deferred half marked); `docs/lean-mvp-implementation-note.md` — Section 0 deliverable; `CONTEXT.md` adds headline/summary/material-change/representative.
* `ROADMAP.md` — `R` stayed `building` but notes `20260830_0019` and supersession; `D2b`/`F` notes updated to say embeddings deferred and judge is the load-bearing piece; `O` notes Llama+DeepSeek supersede Gemini-first.
* `STATUS.md` / GitHub Issue #1 comment at <https://github.com/namwaafetp-commits/EpiSignal/issues/1#issuecomment-5468224004> — same supersession summary.

## Tests added

New test modules (all pass):

* `packages/backend/tests/test_dedupe.py` — +3: near-exact window merge, outside-window stays separate, identical title outside near-exact band still needs body.
* `packages/backend/tests/test_event_judge.py` — decide `AMBIGUOUS` band, judge same/different/unavailable/rejected, wired assembly attaches vs creates new vs prefers new when unavailable/unscope.
* `packages/backend/tests/test_event_summarize.py` — `should_resummarize` on new, material count change, death change, duplicate-report skip, article-count threshold, 24h age; source ranking (official first, quantitative next); the DeepSeek pass (accepted/rejected/unavailable).
* `apps/api/tests/test_events_api.py` — list shapes + filter passthrough, detail (sources/observations/summaries, publication datetime visible), 404, sources endpoint, observations history preserved.
* `apps/web/src/lib/api-events.test.ts` — list shape guard, fetch failure vs shaped success, detail 404.
* `packages/backend/tests/test_pipeline_fixture.py` — lean MFA acceptance fixture shape (30, 4 near-duplicates of one story, 26 representatives, 3-count follow-up chain, geography/disease separation, irrelevant rejected, unknown kept).
* Updated: `packages/backend/tests/test_config.py` (review threshold + resummary knobs), `apps/api/tests/test_migrations.py` (now 0019 + purpose constraint), `apps/api/tests/test_openapi.py` (4 new route paths), `packages/backend/tests/test_models.py` (event_summaries table + enum columns 28), `packages/backend/tests/test_event_seams.py` (read.py allowed), `packages/backend/tests/test_schedule_chains.py` (SUMMARIZE after MATCH), `packages/backend/tests/test_event_protocol.py` (summary surface), `packages/backend/tests/test_event_repository.py` (title propagation + source title batch + observation dedup).

## Tests run & verification

`corepack pnpm verify` — exit 0:

* `uv run ruff format --check .` — pass (4 files reformatted, 260 pass).
* `uv run ruff check .` — pass.
* `corepack pnpm --filter @episignal/web exec prettier --check .` — pass.
* `corepack pnpm lint` — pass (`eslint`, `ruff check` across 129 source files).
* `corepack pnpm typecheck:web && uv run mypy apps/api/src packages/backend/src` — `Success: no issues found in 129 source files`.
* `corepack pnpm test` — 1172 Python tests passed, 1 xfailed (`test_a_wednesday_follow_up_joins_mondays_event_and_updates_it` kept strictly expected because its `assemble` helper does not wire the summarizer), 2 warnings (deprecated httpx import + deprecated 422 constant).
* `corepack pnpm test:web` — 95 web tests passed, 11 files (new `api-events.test.ts` adds 5).
* `corepack pnpm contracts:check && corepack pnpm build` — openapi → index.d.ts matches, Next 16 production build compiled in ~79s (`/events`, `/events/[publicId]` are dynamic `ƒ`; admin reviews static).

## AI models configured

Roster is the single source of truth, seeded from `database/seeds/ai_models.json` → `ai_models` (active rows):

* `meta-llama/llama-3.1-8b-instruct` (`purpose=triage`, active) — cheap classifier and ambiguous-match judge.
* `deepseek/deepseek-v4-flash-0731` (`purpose=event_summary`, active) — event summarizer (DeepSeek).
* `google/gemini-3.1-flash-lite` / `google/gemini-3.5-flash-lite` (general, active) — kept for non-triage ladder; not the MVP's everyday model.

`CLASSIFIER_MODEL` / `SUMMARIZER_MODEL` env keys in `.env.example` are informative placeholders: the roster resolves them; a purpose change is one row edit plus `db:seed`.

## Known limitations

* `embed` stage still rides the `DAILY_CHAIN` as scaffolding (`LocalBgeM3Provider`, pgvector index 1024) but is not load-bearing for matching: matching is deterministic + near-exact dedup + judge; embedding at most adds to the score and is allowed to remain inactive without degrading surveillance quality.
* GDELT retrieval watermark / `gdelt_*` settings are the existing connector's cadence, not a full `previous_successful_end - overlap_minutes -> current_time` loop against an explicit `last_successful_fetch_at` row; the pipeline runner tracks windows via `DiscoveryWindow` and `pipeline_runs` rather than a single watermark cell.
* `events.geometry` + PostGIS stay, but map rendering still reads the radar GeoJSON helpers; the full `MapLibre`-world-map-on-the-events-surface is a `H`-item (the homepage map exists as the radar signal map; `/events` is the lean event feed per the plan's "Optional simple world map if already easy").
* Article-body hash dedup and the `normalized_title` equality path still ride the discovery-stage `title_duplicate_of` seam (discovered via GDELT title) separate from the prebody dedupe stage, which is the verified split; collapsing them into one dedupe run is a later refactor, not a correctness fix.

## Deferred Phase 2 features

Multilingual ingestion, BGE-M3, pgvector story-group retrieval, advanced PostGIS, natural-language search, personalized alerts, subscriptions, mobile app, forecasting, AI chat, advanced risk scoring, Elasticsearch/OpenSearch, Kafka, Redis/Celery/Elastic queues, Kubernetes/microservices.

## Recommended next validation experiment

A 48-hour run of the `summarize:events` stage against the live ledger with `--dry-run`-style logging of every `AMBIGUOUS` judgement and every `should_resummarize` decision:

1. Without enabling a new model row, record the trailing 48h `spend:report` for the triage vs judge vs summary purposes.
2. Confirm that duplicate articles never increment a summary version and that `case count changed -> events -> new version` fires exactly once per genuine follow-up.
3. The one-week-old `monday_then_wednesday` xfail (``expectedFailure``) should flip to pass after the summarizer is wired into the calibration `assemble` helper; keep it as the spec for 1→2→3 observation summarization.

## Estimated capacities

With `GDELT_POLL_INTERVAL_MINUTES=15`, `GDELT_MAX_RECORDS=250`, `gdelt_retry_batch_size=50` and a single worker:

* **Candidate articles/day capacity:** ~250 articles per poll * 96 polls/day at full queue = steady-state dominated by the GDELT discovery limit. Practically, 100–300 candidates/day is comfortable at the `GDELT_MAX_RECORDS=250` cap; the lean MVP deduplicates them before any AI cost is incurred.
* **Expected AI calls/day (at ~200 candidates/day, ~50–80 representative stories after dedup):**
  * classification (Llama 3.1 8B, title+snippet, one per representative before grouping): ~30–50 calls/day.
  * ambiguous-match judge (only the ambiguous band, roughly 1–3% of candidates at the 0.55/0.60 thresholds): 1–5 calls/day.
  * event summaries (DeepSeek, one per materially-changed event, `resummary_max_age_hours=24`, `resummary_new_article_count=3`): 2–8 calls/day at the fixture's 6 events.
  * Total ~40–65 AI requests/day at steady state; dominated by classification. `ai_max_requests_per_run=200` and `ai_max_cost_usd_per_run=0.50` act as per-run guards; the trailing-30-day `spend:report` ledger is the control.
* **Expected DB growth (English-only, Postgres, small VPS 2–4 vCPU / 4–8 GB RAM):**
  * Raw throughput: ~200 signal rows/day, ~3–6 new events/day, ~5–10 observations/day, ~2–5 summaries/day.
  * Monthly: ~6000 signals, ~100–180 events, ~150–300 observations, ~60–150 summary rows. A typical `ai_requests` ledger row is ~200 bytes. At 50 requests/day = ~1 row/day per request → ~1500 rows/month. The full database grows at ~1–2 MB/day compressed text plus ~6 GB gazetteer geometry index on the heap. A 2 vCPU / 8 GB VPS holds the heap comfortably; pgvector stays on its own ivfflat-free HNSW index sized to the embedding column (currently not load-bearing).

## MVP success criteria — assessment

1. English global news retrieved automatically — **pass** (GDELT English-only query rules + `discover_runner` verified).
2. Syndicated duplicates do not generate repeated AI calls — **pass** (RapidFuzz `title similarity >= 92 within 48h` + 48h window added; checked in `test_dedupe`).
3. Irrelevant articles rejected cheaply — **pass** (keyword-gated `retrieve` + `triage` cheap classifier with `not_public_health` vs `infectious_disease`; checked in `test_ai_triage` + fixture `football fever` irrelevant).
4. Related follow-up reports attach to the same event — **pass** (deterministic scorer + `follow_up` delta; calibration `chiang_mai_three -> 1 event`).
5. Geographically distinct outbreaks do not auto-merge — **pass** (`CONFLICTING_ADMIN1` hard guard + spatial precision: Phuket vs Chiang Mai -> 2 events; calibration pinned).
6. Changing epidemiological counts remain as observation history — **pass** (observations are additive rows, never overwrites: 42 -> 68 -> 91 remain three rows, `event_observations` with dedup guard).
7. Event summaries update only when something meaningful changes — **pass** (`should_resummarize` on counts mismatch / 3+ unsummarized / >24h; duplicate with no count change returns false; checked in `test_event_summarize`).
8. Every visible claim remains traceable to sources — **pass** (sources expose `source_name`, `title`, `published_at`, `url`; observations carry `data_as_of` + counts per source; `/events/{public_id}/sources` and `/events/{public_id}/observations` endpoints).
9. System runs comfortably on one small VPS — **pass** (one FastAPI process + Python worker invocations + Postgres; `verify` production build succeeds; resource target 2–4 vCPU / 4–8 GB RAM).
10. Architecture can later add multilingual embeddings without rewriting core — **pass** (`EmbeddingProvider` seam + `purpose` roster + `events/match.SIMILARITY_WEIGHT` remains additive-only; Phase 2 multilingual would flip query-rule `language` and the `local` embedding provider without changing model contracts).

## Stages wired

* `match:events` (`event_runner.py`) + `summarize:events` (`summarize_runner.py`).
* `test:pipeline` (`test_pipeline_fixture.py` with `30_candidates.json`).
* `corepack pnpm verify` green at this commit.
