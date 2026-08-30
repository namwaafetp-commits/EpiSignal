# Lean MVP Implementation Note

**Date:** 2026-08-30
**Scope:** Section 0 of the Lean MVP Implementation Plan — what exists, what is
reused, what is simplified, and what old Phase 1 decisions are superseded.

## What exists

The repository is a mature, verified Phase 1 build, not a specification
skeleton. `corepack pnpm verify` is green: 905 Python tests, 58 web tests,
ruff/eslint/mypy/tsc clean, and a production build. The working pipeline is:

```text
ingest WHO/ECDC -> GDELT discover (English-only query rules)
  -> keyword gate -> retrieve body
  -> dedupe -> triage (Llama 3.1 8B, purpose-scoped rung)
  -> pregroup (story_groups, default-off)
  -> cluster extraction -> geocode -> event assembly -> observations
```

Key subsystems already present:

| Area | Where | State |
| --- | --- | --- |
| GDELT English-only retrieval | `ingestion/gdelt/`, `discover_runner.py`, query-rule seed pinned to English | verified |
| URL normalization | `ingestion/urls.py::canonicalize_url` | verified |
| Title normalization | `ingestion/normalize_title.py::normalize_title` | verified |
| Dedupe (exact + title/body Jaccard) | `ingestion/dedupe.py` | verified |
| Story groups (`story_groups`, `story_group_members`) | `models/story.py`, pregroup | verified |
| Cheap structured triage (relevance + disease + place) | `ai/triage.py`, schema `TriageVerdict` | verified |
| Grounded epidemiological extraction | `ai/extract.py`, schema `Extraction` | verified |
| Event tables (`events`, `event_signals`, `event_observations`, `event_locations`) | `models/event.py` | verified |
| Deterministic event matching with hard guards | `events/match.py`, `events/score.py` | verified |
| Manual review queue | `review/`, `models/review.py` | verified |
| AI cost ledger (`ai_requests`) | `ai/repository.py`, `ai/spend.py` | verified |
| Provider abstraction (OpenRouter + Gemini adapters) | `ai/protocol.py`, `ai/routing.py`, `ai/ladder.py` | verified |
| Public API (health, signals, radar, admin, reviews) | `apps/api/` | verified |
| Next.js web shell + radar | `apps/web/` | verified |
| Scheduler chain with advisory lock | `schedule/` | verified |

## What is reused

The domain model is preserved as-is. The plan's proposed `articles`,
`event_sources`, and `ai_usage` tables map onto the existing `signals`,
`event_signals`, and `ai_requests` tables; there is no benefit to renaming
verified tables, so the plan's concepts are implemented on the existing schema.

- The existing provider seam (`ChatModel`, `Ladder`, purpose-scoped rungs) is
  used for the new passes. The roster seed already carries the two models the
  plan selects:
  - `meta-llama/llama-3.1-8b-instruct` with `purpose=triage` (the cheap classifier)
  - `deepseek/deepseek-v4-flash-0731` with `purpose=event_summary` (the summarizer)
- The existing triage pass already produces the plan's classification shape
  (`relevant`, `category`, `event_type`, `disease`, `country`, `admin1`,
  `admin2`, `confidence`). Phase C of the plan is therefore verification, not
  construction.
- Event matching, observations, cost logging, and the review queue are reused
  unchanged, except for the additions listed below.

## What is added (the genuine gaps)

1. **RapidFuzz near-exact dedup** — the plan's Section 9 rule
   (`title similarity >= 92 AND publication time difference <= 48h`) is added
   to the dedupe matcher as an additional near-duplicate path, behind
   configurable thresholds. `rapidfuzz` becomes a dependency.
2. **Ambiguous-event LLM judge** — a deterministic `AMBIGUOUS` band is added to
   the match decision (between the auto-attach and review thresholds), and an
   LLM judge decides `same_event` for that band. A false merge stays worse than
   a duplicate event, so the judge defaults to "new event" when uncertain.
3. **Event summarization** — a `summarize` stage that (a) detects material
   change since the last summary, (b) picks up to six representative sources,
   and (c) asks the DeepSeek summarizer for a versioned headline/summary/status.
   The events table gains `headline`, `summary`, `article_count`,
   `latest_report_at`, and `last_summarized_at`; a new `event_summaries` table
   keeps the versioned history.
4. **Events API** — `GET /api/v1/events`, `GET /api/v1/events/{public_id}`,
   `/sources`, and `/observations` with the plan's filters, added to the
   existing FastAPI app and the generated contracts.
5. **Event web pages** — an events list and an event detail page (overview,
   latest counts, observation timeline, traceable sources) in the Next.js app.
6. **Fixture dataset + pipeline test** — a synthetic 20–30 article fixture and
   `pnpm test:pipeline`, which runs ingestion, dedup, fake classification, event
   matching, observation creation, and fake summarization with zero network
   calls.
7. **Documentation** — `docs/lean-mvp-architecture.md`, updated `CONTEXT.md`,
   and a resolved issue #1 (embeddings marked superseded).

## What is simplified / deferred

The following Phase 1 decisions are explicitly **superseded** for the MVP and
are marked so in the docs and the roadmap (not deleted — history is preserved):

- **Embeddings and pgvector** (`signals.embedding`, the explicit embed runner,
  BGE-M3, HNSW index). The MVP does not use semantic similarity; deterministic
  match guards plus the ambiguous judge replace it. The embedding code remains
  dormant Phase 2 scaffolding and is excluded from the daily chain.
- **Gemini-first ladder** — resolved per the plan: Llama is the classifier,
  DeepSeek is the summarizer. The Gemini adapters and roster rows stay
  (providers remain configurable), but the MVP's model selection is
  Llama + DeepSeek via OpenRouter.
- **Multilingual ingestion** — the query library stays pinned to English.
- **Natural-language search, PostGIS-heavy features, forecasting, alerts,
  mobile app, AI chat, subscriptions** — deferred to Phase 2, per the plan.

## Processing statuses

The plan's status vocabulary (§5) is a rename of the verified vocabulary that
exists today. The existing values are kept (matching the plan's intent that
processing be idempotent), and the summary stage adds no new signal status:
summarization is keyed off `events.last_summarized_at` and the `event_summaries`
history table, so rerunning a summary pass is idempotent by construction.
