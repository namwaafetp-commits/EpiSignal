# Surveillance review corrections report

## Fixes

- Unknown disease-group filtering now treats a missing disease, an explicitly
  unknown mapped slug, and any canonical slug absent from the mapping authority
  as `unknown`. Display and SQL filtering therefore agree.
- `/events` filter links now copy the complete current query and change only the
  selected parameter. Active values clear only themselves. Disease-group and
  host labels use one shared web representation with human-facing text.
- New Mistral requests now validate only `FlexibleEventSummary`. A legacy-shaped
  model response is rejected through the normal shape-rejection path. The old
  `EventSummaryVerdict` model and renderer remain only for persisted legacy
  records.
- Flexible homepage summaries no longer render the separate legacy
  `Public/global risk` block. Historical summaries retain their old headings.

## Regression tests

- Unmapped canonical disease slug is returned by the `unknown` event filter.
- Combined `/events` filter-link cases preserve host, disease group, country,
  status, and disease parameters; active-filter clearing is isolated.
- Human-facing disease-group and host labels are asserted.
- Legacy-shaped new-model output is rejected, while a persisted legacy verdict
  still renders with legacy headings.
- Flexible homepage detail content omits the legacy risk block.

## Verification

```text
corepack pnpm verify: PASS
web tests: 125 passed in 15 files
python tests: 1460 passed, 2 skipped, 2 warnings
format: PASS; 308 Python files already formatted; Prettier clean
lint: PASS; Ruff and ESLint clean
typecheck: PASS; TypeScript and mypy clean, 147 Python source files
contracts: PASS; generated contract diff clean
build: PASS; Next.js production build completed and generated 6/6 static pages
migration head: 20260908_0023 (head)
```

The skipped tests require `EPISIGNAL_TEST_DATABASE_URL`. Existing Vite and
dependency deprecation warnings remain. No production operation was performed.

## Invariants

Matching logic and thresholds, Gemini responsibility, DeepSeek routing, Mistral
model selection, GDELT behavior, monitoring behavior, cron, historical AI
backfill, and requeue behavior are unchanged. No new migration was added; the
existing migration `20260908_0023` remains the head.

## Git and deployment

Fix commit: `bc51db3`, based on `88fd87f`. This is local source work only:
NOT DEPLOYED; VPS NOT ACCESSED; COOLIFY NOT ACCESSED; PRODUCTION DATABASE NOT
MODIFIED.
