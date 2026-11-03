# Event summary gate correction report

**Date:** 2026-09-12
**Scope:** Initial DeepSeek event summaries after event creation

## ROOT CAUSE

The two 18:00 events were newly created, so `last_summarized_at` was null.
Before this correction, `should_resummarize(...)` returned true for that state,
and the event data carried no requirement for disease, location, counts, or a
non-empty observation. The skip therefore occurred after that decision, in the
`wiring.model is None or wiring.spec is None` branch of
`schedule/stages.py::_summarize`.

The supplied production output did not expose whether the missing wiring came
from a missing OpenRouter key or a missing active purpose-specific roster row;
the old stage collapsed both cases into generic `skipped`. Production was not
accessed for this correction. The local registry/seed contract resolves
`deepseek/deepseek-v4-flash-0731` with provider `openrouter` when an OpenRouter
key and the event-summary roster row are present, proven by the wiring test.

Source availability was also not represented in the old stage telemetry. The
new event path now requires at least one linked source with non-blank clean
article text before a model call.

## FIX

- Initial summary rule: `last_summarized_at is None` remains immediately due,
  independent of structured observations, disease, location, or counts, when a
  usable linked source exists.
- Existing-event resummary rule: a summarized event refreshes only on a
  material observation change, at least three unsummarized linked articles, or
  an age beyond the configured 24-hour threshold.
- No-source behavior: skip safely without a provider call.
- Telemetry added: `skipped_no_change`, `skipped_no_model`, and
  `skipped_no_sources`, while retaining aggregate `skipped`.
- The standalone summary runner emits the same skip counters.
- No migration, prompt, relevance, grouping, matching, discovery, cron, or
  production configuration change was made.

## TESTS

- New event with no counts/observation and article: passes the due gate and is
  sent to the model.
- New event with unresolved disease/location and article: passes the due gate.
- New event with no usable article text: skips safely.
- Existing summarized event with no material change: skips.
- Existing summarized event with material observation change or sufficient new
  article evidence: summarizes.
- DeepSeek wiring: resolves model
  `deepseek/deepseek-v4-flash-0731` through `OpenRouter`.
- Legacy summary rendering and existing summary tests remain green.

## VERIFY

`corepack pnpm verify` passed:

- Python: 1,530 passed, 2 skipped, 2 existing deprecation warnings.
- Web: 125 passed.
- Format: passed.
- Lint: passed.
- Typecheck: passed; 149 Python source files reported no issues.
- Contracts: generated and checked with no diff.
- Build: passed; Next.js production build completed.
- Alembic: `20260911_0024` (head).

## GIT

- Previous HEAD: `ec11e55`
- New HEAD: commit containing this report.
- Remote HEAD: `origin/codex/next-iteration` before push; updated to the new
  commit by the authorized branch push.
- Working tree: clean after commit/push.

## PRODUCTION

- Deployed: NO
- Production DB changed: NO
- VPS accessed: NO
- Coolify accessed: NO
