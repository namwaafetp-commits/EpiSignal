# Handoff — F Lite model check

F Lite added a small deterministic model comparison tool on
`codex/f-lite-model-check`. It uses 20 triage and 20 extraction fixtures, the
existing AI contracts/grounding checks, explicit provider calls, finite request
and dollar caps, and JSON results under `benchmarks/results/`. No benchmark
database or production configuration was added. The database-heavy F harness
proposal is superseded by F Lite for MVP and deferred post-MVP.

Triage live evidence completed for Llama 3.1 8B and Mistral Small 24B; the
extraction smoke timed out before producing quality evidence. Keep the
production roster unchanged until extraction evidence exists.
