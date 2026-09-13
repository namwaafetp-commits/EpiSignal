# Production metadata extraction repair report

1. Root cause

   The extraction and triage prompts treated article text/snippets as evidence but did not explicitly treat the supplied title as evidence. The extraction validator also grounded accepted claims against body text only. As a result, explicit disease and country names in production headlines could be discarded. Event matching then had no deterministic title/body fallback, so otherwise obvious events were stored without disease or country metadata.

2. Files changed

   Changed `package.json`, the AI extraction/prompt/validation modules, event documents and repository, and the related tests. Added `packages/backend/src/episignal_backend/metadata.py`, `metadata_repository.py`, `metadata_repair_runner.py`, and `packages/backend/tests/test_metadata.py`.

3. Implementation by step

   Titles are now explicit extraction and triage evidence. Accepted metadata is resolved in this order: extraction metadata, triage metadata, exact local disease/country/admin1 references in title/body, then unresolved. The resolver uses the reviewed disease vocabulary, static country aliases/codes, and seeded gazetteer admin1 data; ambiguous places remain null. New event assembly receives disease, country, and admin1 metadata without requiring stored coordinates. Existing dashboard centroid fallback behavior and frontend MapLibre code were left unchanged. The repair runner selects only events missing country and/or disease, follows linked source signals, updates existing rows in place, defaults to dry-run, and reports counts.

4. Tests added

   Regression coverage includes South Africa/measles, India/malaria, DRC/Ebola, Australia/H5N1 bird flu, Wisconsin/admin1, ambiguous Springfield, ambiguous generic Congo, extraction-over-triage priority, invalid metadata fallback, unknown country codes, title-grounded extraction, event creation, cluster disease selection, and dry-run versus apply repair behavior. The resolver is entirely local and has no geocoder or network path.

5. Test, lint, typecheck, and build results

   `corepack pnpm verify` passed. Results: web 105 tests passed; backend/API 1241 tests passed; Ruff formatting and lint passed; web lint and TypeScript typecheck passed; mypy passed on 134 files; contract generation/check passed; Next production build passed. Two pre-existing Starlette/httpx deprecation warnings remain. No frontend files were changed.

6. Repair runner command

   Review first with:

   `corepack pnpm metadata:repair -- --dry-run`

   Apply only after explicit operational approval with:

   `corepack pnpm metadata:repair -- --apply`

   Neither command was run against production for this task.

7. Expected production effect

   Future events with explicit, unambiguous disease and location evidence should receive `disease_id`, `country_code`, and admin1 where available during normal processing. Existing affected events can be repaired in place, and dashboard read-time centroid fallback can map country/admin1 without event lat/lon. Ambiguous or unsupported evidence remains unmapped instead of being guessed.

8. Remaining risks

   Coverage still depends on the seeded disease vocabulary, country aliases, and gazetteer. Multi-country or multi-admin1 stories can remain unresolved conservatively. The repair has not been run on live data, so production counts and event-specific edge cases remain unverified. Existing non-null event metadata is not overwritten by the repair.

9. Commit SHA

   `61fed26978bc35a060342cffce396a9d8b0f62a6`

10. PR URL

    Not created. No remote push or deployment was performed; the fix is on local branch `codex/next-iteration`.
