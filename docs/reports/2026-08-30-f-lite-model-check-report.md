# F Lite — Lean model check report

**Date:** 2026-08-30  
**Branch:** `codex/f-lite-model-check`  
**Baseline:** `cda5efe120ab92fe42f051928df1acbe6cc1c228`

F Lite compares only `triage` and `extraction` using committed synthetic JSON
fixtures and explicit provider calls. It has no benchmark database, migration,
API, scheduler, dashboard, automatic roster change, or production routing
integration. The database-heavy F proposal is superseded by F Lite for MVP and
deferred to post-MVP.

## Fixtures and tool

`packages/backend/tests/fixtures/model_check/triage.json` and
`extraction.json` each contain 20 stable cases. The runner is
`corepack pnpm model:check`; it reuses the existing Pydantic contracts,
grounding validator, provider adapters, roster seed prices, and `cost_usd`.
Results under `benchmarks/results/` retain the git SHA, fixture version, model
IDs, guard, raw answers, deterministic scores, token counts, latency, and cost.

## Live evidence

Triage completed for two existing cheap OpenRouter models:

| Model | Cases | Recall | False negatives | Accuracy | Cost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Llama 3.1 8B Instruct | 20 | 0% | 0 | 0% schema acceptance | $0.000058 |
| Mistral Small 24B | 20 | 100% | 0 | 90% | $0.000143 |

Llama's responses were all schema-rejected; they are recorded as schema
failures, not silently counted as false negatives. Mistral produced two false
positives and no missed relevant cases in this small sample.

Extraction live smoke was attempted under a four-request/$0.02 cap, but the
provider did not complete within the configured timeout. The explicit `not_run`
record is retained at `benchmarks/results/2026-08-30-model-check-extraction.json`;
no extraction quality or cost claim is made.

## Recommendation

**KEEP CURRENT production roster pending extraction evidence.** The triage
sample favors Mistral on usable structured output and recall, but the sample is
too small and extraction was not completed. No production model, tier, active
flag, route, threshold, scheduler, or embedding setting was changed.

## Verification

- `corepack pnpm verify`: PASS — 95 web tests, 1184 Python tests, 0 xfails;
  existing deprecation/Vite warnings only.
- `corepack pnpm test:pipeline`: PASS — 16 tests.
- `uv run pytest packages/backend/tests/test_model_check.py -q`: PASS — 9
  offline tests, no network calls.

## How to extend

Add a case with a unique `case_id`, exact evidence, and expected values accepted
by the existing contract. Run the offline test, then invoke
`corepack pnpm model:check -- --purpose <purpose> --models <comma-separated-seed-model-ids> --max-cost-usd <cap>`.
Inspect raw scores and failure categories; do not infer a roster change from
one small run. The heavy multi-purpose benchmark history framework remains
post-MVP.
