# Final simplified three-model pipeline report

## 1. Scope and model stack

Implemented the requested final pipeline on the expected `7adf667c76e797b3ba175e222913a81224d3f259` baseline. Active purpose routing is DeepSeek V4 Flash (OpenRouter) for relevance, Gemini 3.1 Flash-Lite (direct Google) for identity extraction, and Mistral Small 3.2 (OpenRouter) for event summaries.

## 2. Pipeline order

The daily chain is discover → deduplicate → classify → retrieve → extract → match → summarize. Discovery stores title and a bounded opening excerpt (falling back to the title for bodyless stubs); retrieval and article cleaning occur only after relevance classification.

## 3. Relevance classification

Classification sends only TITLE, SNIPPET, SOURCE, and PUBLISHED_AT and validates `{relevant, confidence, reason_code?}`. It does not extract disease or location, has no fallback model, and writes one cost-ledger request per signal.

## 4. Identity extraction

Gemini receives the exact production extraction prompt and returns only disease plus a locations array of `{town, country}`. A missing disease or event country triggers at most one same-model IDENTITY REPAIR request; the deterministic best valid partial is retained when repair is incomplete.

## 5. Deterministic normalization

Whitespace and case are normalized, country aliases/codes are resolved through the reviewed vocabulary, known diseases resolve to canonical IDs, unknown disease text is retained with a null ID, and exact duplicate locations are removed. No model is asked to normalize identity.

## 6. Grouping and matching

Grouping requires exact disease identity, exact normalized location overlap, and the configured time window. Town/local identities do not collapse into country-only identities; multi-location overlap is supported; fuzzy distance, embeddings, and LLM judges are not used.

## 7. Material-change behavior

Event summaries are generated once per grouped event. A never-summarized event or a source linked after the previous summary is due for regeneration, using the EventSignal attachment timestamp so backlogged older articles are not missed.

## 8. Summary generation

Summary input contains all linked clean article sources with title, publication time, source, and article text, plus event context and observation provenance. Deprecated extraction fields are not supplied. Fixed fallback language remains in the prompt and summaries are rendered with the required flash-brief labels.

## 9. API, dashboard, and map

Event observations now expose signal provenance, report time, notes, and material facts rather than deprecated numeric extraction fields. Event detail exposes all stored event locations, while the existing dashboard/map continues to use the canonical event location. Review and radar reads tolerate identity-only rows.

## 10. Persistence and backward compatibility

Existing database columns and historical rows are preserved. New extraction writes contain only disease text, locations, and schema version 5; no migration, requeue, production seed, or production database write was run.

## 11. Verification

Focused final-pipeline tests passed (27 tests), along with repository lint, mypy, web tests (107), contract generation, and production web build. `corepack pnpm verify` was run; its formatting, lint, typecheck, and web-test stages passed, but the full Python suite ended with 155 legacy failures because existing tests still assert the retired rich-extraction, batched-classification, delta/judge, numeric-observation, and radar contracts. This gate is therefore not claimed as passed.

## 12. Safety and operational boundaries

Production DB writes: not run.

Deploy/merge: not run.

Scheduler/requeue changes: not run.

Production model-registry/config changes: not run; the database roster still needs an authorized configuration update for the exact final-purpose rows, especially Mistral Small 3.2, before live execution.
