# Plan — Pipeline Funnel v2

**Date:** 2026-08-29
**Spec:** [2026-08-29-pipeline-funnel-v2-design.md](../specs/2026-08-29-pipeline-funnel-v2-design.md)
**Branch:** create `codex/pipeline-funnel-v2` in a separate worktree from the
current `codex/manual-review-queue` head (it carries unmerged prerequisite
work). Never check out a feature branch in the primary tree.
**Worker contract:** test-first per task; tick the task in the commit that
completes it; run the scoped tests before committing; no task spans modules
it does not own. Stop after task 14 and hand back to the planner. Do not mark
the item verified.

## Tasks

1. **Keyword rule vocabulary.** Migration + model for `keyword_rules`
   (id, rule_text, is_active, created_at), seeded with the D1 list, plus
   `KeywordRuleSeed` in `seeds.py` and `seed_runner` wiring. Table updates are
   additive; downgrade drops it. Test: seed idempotence, active-only read.
2. **`filtered` status.** Add `FILTERED = "filtered"` to `ProcessingStatus`,
   migration for the pg enum value, and the web `PROCESSING_STATUSES` set in
   `apps/web/src/lib/api-radar.ts`. Radar queries must exclude it the way they
   exclude `duplicate`. Tests: enum round-trip, radar exclusion, web validator
   accepts `filtered` in a feed fixture.
3. **Gate function.** `ingestion/keyword_gate.py`: `classify_title(title,
   rules) -> GateDecision` with the pass-bias rules of D1 and the matched rule
   recorded. Pure function, no DB imports. Tests: pass on disease name,
   pass on context term, filter on clean headline, case-folding, empty-rule
   behaviour (no active rules = pass everything, never filter).
4. **Gate into the chain.** New step in the extract stage before selection:
   select `fetched` signals with null body, run `classify_title`, write
   `filtered` + matched-rule provenance on reject, enqueue the rest for
   retrieval. Counts surfaced in the stage summary. Tests: fake repository
   covering reject/pass/empty mix; nothing deleted.
5. **Deferred retrieval.** GDELT connector promotes without fetching
   (`raw_text = null`, `fetched`); the gate's pass path runs
   `ArticleFetcher`, then normalization. Unfetchable -> existing
   `retrieval_failed` review path. WHO/ECDC unchanged. Tests: connector
   promotes without a fetcher call; pass path fetches exactly once; fetch
   failure opens the review case; WHO ingest still fetches at ingest.
6. **Enable pre-group.** Flip the flag default, wire the extract stage to
   resolve open story groups before selection. Deferred members return to
   selection on expiry exactly as the pre-group module already does. Tests:
   group resolution, expiry, and the no-group fallthrough to normal
   per-article extraction.
7. **Cluster extraction schema v3.** `ai/schema.py`: version-3 payload with
   per-claim `source_index`, `extraction_json_schema(v=3)` variant, and
   `StoredExtractionPayload` reading v3 rows. Tests: schema round-trip, v2
   rows still readable (backfill contract), invalid source_index rejected.
8. **Cluster prompt + validator.** `ai/prompts.py`: cluster prompt carrying up
   to four members (title + truncated body, `source_index` labels, same
   grounding rules, spans copied in the cited member's language).
   `ai/validate.py`: validate each span against the cited member's text only.
   Tests: grounded multi-member acceptance, span-in-wrong-member rejection,
   out-of-range index rejection, four-member truncation bounds.
9. **Cluster extraction pass.** `ai/extract.py`: `run_cluster_extraction` —
   one climb per open group's members; accepted -> store v3 payload on the
   representative, mark members `duplicate` with
   `duplicate_of_signal_id`; rejected -> fall back to per-article extraction
   for that group; cost rows with `batch_size = len(members)`. Tests:
   acceptance marks members, fallback runs per-article, budget guard stops
   cleanly mid-groups, member marking preserves their rows.
10. **Chain wiring.** Extract stage order: gate -> retrieve -> pre-group
    resolve -> cluster extraction -> per-article extraction for the
    ungrouped remainder. Summary counts extended (gated, retrieved, clusters,
    fallbacks). Tests: end-to-end fake run over a mixed backlog.
11. **Observability.** `spend:report` groups cluster rows visibly
    (`batch_size > 1`), and the stage summary prints
    `gated=/retrieved=/clusters=/fallbacks=`. No new tables. Tests: report
    shape, summary keys.
12. **Docs.** `CONTEXT.md` funnel diagram update; glossary entries for
    `keyword gate`, `story group`, `cluster extraction`; ADR capturing D5's
    representative-carries-extraction decision and its revisitable condition.
13. **Live proof.** Run the chain once on the live database with the gate and
    pre-group on. Record: gated count, retrieved count, cluster count,
    fallback count, request count and cost versus the 2026-08-29 baseline
    (105 requests / 43 extracted / ~$0.30 ledger). No review-case resolution
    purely for demonstration; synthetic fixtures follow the synthetic rule.
14. **Review, verify, report.** Load `code-review`, then `verify-and-stop`;
    run the real `corepack pnpm verify`; write
    `docs/reports/2026-08-29-pipeline-funnel-v2-report.md` with exact output;
    update the worker-owned baseline in `STATUS.md`; hand back. Do not mark
    the item verified.

## Scope guard

Do not: embed similarity models, touch D2b, change the geocode ladder, change
event matching weights, modify the radar read model for cluster display,
delete or re-enrich existing v2 extraction rows, wire the Gemini batch API, or
resolve live review cases. Existing v2 rows stay readable through backfill;
they are never migrated in place.
