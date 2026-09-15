# Surveillance Dimensions and Flexible Event Summaries

## Goal

Add deterministic disease grouping, evidence-specific human/animal host classification, and flexible event summaries without changing the existing discovery, matching, monitoring, or Gemini responsibilities.

## Architecture decision

Disease grouping is a derived domain value. A single maintained registry maps every current canonical disease slug to one `DiseaseGroup`; aliases continue through the existing canonical disease resolver before group lookup. Unknown or unresolved diseases use `unknown`. No disease-group column or AI prompt field is added.

Host sector is signal evidence, so it is persisted as an additive nullable value on the signal classification record. DeepSeek classification owns the value. Missing historical values read as `unknown`. Event host sector is derived at read/finalization boundaries from attached signal values using explicit precedence: `both`, then human plus animal, then human, then animal, then unknown.

Event summaries keep the existing event headline as the canonical title when present. New Mistral output is a strict `{title, bullets, takeaway}` contract with 3–5 non-empty bullets. The renderer emits title, bullets, and takeaway. Legacy persisted summary payloads remain readable through a compatibility renderer and are not backfilled.

## API and UI

Event and signal responses gain additive `disease_group`, `disease_group_label`, and host-sector fields where applicable. Dashboard filtering supports independent host-sector and disease-group selectors; Human includes `human` and `both`, Animal includes `animal` and `both`, and All includes every value. Cards show compact disease, group, and host metadata without adding map clutter.

## Non-goals and invariants

- No disease normalization changes.
- No event matching thresholds, merge/split behavior, or coordinates change.
- No GDELT breaker or monitoring threshold changes.
- No Gemini host classification or expanded Gemini responsibility.
- No historical AI backfill.
- No production access, deployment, cron changes, requeue, or broad backfill.

## Verification

Focused backend, API, and web tests cover mappings, host classification/derivation, combined filters, summary validation, malformed JSON, and legacy rendering. Changed Python files receive Ruff checks; changed web files receive lint/typecheck. OpenAPI is regenerated and checked when contracts change. `corepack pnpm verify` is the completion gate.
