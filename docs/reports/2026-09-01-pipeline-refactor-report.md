# EpiSignal Pipeline Refactor Report

1. Architecture changes

The daily chain now runs discovery, relevance-only classification, retrieval,
deduplication, extraction, event matching, and event summarization. The normal
chain no longer runs the old metadata triage pass. Classification owns only the
relevance decision; extraction owns epidemiological meaning. Existing event
observation history, conservative matching, summary versioning, MapLibre, and
the WHO/GDELT source architecture remain unchanged.

2. Files changed

The implementation changes the AI documents, prompts, schema, classifier,
extractor, AI repository, retrieval repository, retrieval pass, metadata
resolver, scheduler, generated contracts, and their tests. The deterministic
`metadata_repair_runner.py` entry point was removed. The replacement is
`packages/backend/src/episignal_backend/metadata_repair_ai_runner.py`.

3. Discovery/dedup changes

Discovery remains metadata-first. The classifier receives discovery metadata
before a GDELT body is fetched. Existing canonical-URL/title suppression still
prevents obvious syndicated copies from being fetched, and the existing body
deduplication pass remains after retrieval because it requires article content.

4. Classification behavior and model

Classification now accepts `id`, `relevant`, `confidence`, and optional
`reason_code` only. Its prompt carries TITLE, a bounded SNIPPET, SOURCE, and
PUBLISHED. It cannot return disease, location, counts, or event type. An
irrelevant result is stored as `filtered`; a relevant result is eligible for
retrieval. The existing AI ladder and classification purpose routing are used.

5. Retrieval/cleaning behavior

Only unfiltered, relevant-or-legacy-unclassified discovery rows are eligible
for retrieval. A stored relevant decision overrides the legacy keyword fallback
so the fallback cannot reject a model-approved signal. GDELT's existing HTML
article extraction continues to store clean article prose in `raw_text`, with
the source URL preserved as provenance.

6. Extraction input and model

Extraction receives TITLE plus the stored clean article content, capped by the
existing deterministic input limit. A public single-signal extraction seam now
shares the production prompt, ladder, grounding validation, and cost-recording
path; the AI repair runner uses this seam rather than a metadata-specific model
call.

7. Extraction schema

The existing strict extraction schema remains the source of truth for disease,
locations, epidemiology, dates, transmission, response, and the five ordered
brief points. Every numeric and transmission claim remains grounded by source
span and source index. No database migration was introduced.

8. Deterministic validation behavior

`LocalMetadataResolver` now validates structured extraction/triage fields only:
reviewed exact disease aliases resolve to a disease id, reviewed country aliases
normalize to ISO-2, and admin1 must belong to the supplied country. Invalid or
conflicting geography becomes unresolved. Article title/body text is never
scanned for disease, country, or admin1. Field-level provenance is exposed as
`extraction`, `triage`, or `unresolved`, and conflicts are retained.

9. Event grouping behavior

Event grouping remains after extraction and uses the existing conservative
structured disease/location/time matching path. The refactor does not introduce
fuzzy disease matching, embeddings, external geocoding, or arbitrary LLM event
merges.

10. Material-change behavior

Existing additive observations and material-change detection are preserved.
Unchanged reports attach evidence without forcing a summary regeneration;
material changes continue to drive event-level summary updates.

11. Event-summary schema and prompt

No unrelated summary redesign was introduced. The existing structured,
versioned event-summary contract remains the event-level output and continues
to receive consolidated event evidence only when the existing summary policy
selects the event.

12. Existing metadata repair design

`metadata:repair-ai` is dry-run by default and supports `--apply`, `--limit`,
and `--max-ai-requests`. It selects events missing country or disease, reuses
stored extraction/triage only when the structured fields pass current
validation, and otherwise runs the normal extraction seam on linked clean
signals. It records every applied AI attempt in the existing cost ledger,
reuses no prose inference, combines linked signals conservatively, prints
proposals with field provenance, and refuses to reconcile an event from a
partial linked-signal set after a budget guard trips. No production repair,
deployment, or scheduler run was executed.

Command examples:

```text
metadata:repair-ai --dry-run
metadata:repair-ai --dry-run --limit 20 --max-ai-requests 20
metadata:repair-ai --apply --limit 20 --max-ai-requests 20
```

13. Production-derived regression tests

Metadata tests now permanently cover structured validation, exact reviewed
aliases, admin1/country conflicts, extraction-over-triage priority, provenance,
and the former headline/body false-positive classes. Retrieval tests cover the
model-relevant decision bypassing the legacy keyword fallback. Event matching
tests prove unstructured headline text no longer creates disease or location.

14. End-to-end tests

The production pipeline fixture and dedup suite remain green, and the scheduler
tests now assert the classify stage is present while the retired normal-chain
triage stage is absent. The classifier and retrieval seams are tested together
at their storage boundaries; irrelevant signals are terminally filtered and
are not fetched.

15. Test/lint/typecheck/build results

`corepack pnpm verify` passed in the final run:

- Web: 105 tests passed in 14 files.
- Python: 1,252 tests passed, 0 failures, 2 existing deprecation warnings.
- Ruff format, Ruff lint, web lint, web typecheck, and mypy passed; mypy checked
  134 source files.
- Contract generation/check passed.
- Next production build passed and generated the existing six routes.

`corepack pnpm test:pipeline` also passed: 16 tests in 3.37 seconds.

16. Expected AI calls per 100 discovered articles

At most approximately 5 batched classification requests when the classifier
batch size is 20, followed by one extraction request per relevant article at
the first successful ladder rung. Event summaries are event-level and occur
only for new or materially changed events. Provider failures or schema
rejections can add ladder attempts, bounded by the configured request guard.

17. Estimated token/cost impact

The normal chain removes one full-content metadata-triage request per signal.
Classification adds a small bounded metadata request before retrieval, while
irrelevant signals avoid retrieval and extraction entirely. For 100 discovered
articles, the rough cost is five classification batches plus the relevant
article extraction count and event-summary count; exact USD depends on the
active roster prices and relevance rate. No live cost measurement was run in
this implementation task.

18. Remaining risks

The repository has no dedicated discovery-snippet column, so bodyless GDELT
rows use the title as the bounded classification snippet until a separately
approved schema transition exists. Body-based near-exact deduplication remains
after retrieval by design. Existing legacy triage code and CLI remain available
for compatibility, but are not scheduled in the normal chain. Production
repair still requires human review and explicit approval.

19. Commit SHA

`3e63a946d0fb95ed30ddce4510b0aba1c022ab2f`

20. PR URL

Not created. The plan explicitly excludes an autonomous PR and no external
repository mutation was requested.
