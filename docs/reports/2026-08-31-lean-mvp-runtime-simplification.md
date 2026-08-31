# Lean MVP runtime simplification

Date: 2026-08-31

Before events: 14
Before summaries: 14
Backlog extracted: 131

After events: 145
After summaries: 15
Attached existing: 0
Created new: 131
Unmapped: 130
Remaining blocked: 41

Historical review rows examined: 172
Valid extracted backlog: 131
Invalid extractions: 41
Requeued: 131
New events: 131
Attached existing: 0

Events total: 145
Summaries total: 15
Summaries pending: 130
Exact pending reason: the summary provider was configured and one provider
request succeeded, but the remaining provider requests did not complete within
the bounded validation run. The run was stopped before the first 32-request
batch committed. This was not a missing API key, extraction regeneration, a
full-pipeline rerun, or an intentional skip. No evidence was recorded to
classify it as a rate limit or model-unavailable response.

The 172 historical `NEEDS_REVIEW` rows were examined. The 131 rows with valid
stored extractions were requeued directly to
`EXTRACTED`, then matched and attached to newly created events. The 41 rows
left in `NEEDS_REVIEW` were excluded because their stored extraction was
invalid. No discovery, retrieval, dedupe, triage, or extraction was rerun for
the recovery pass.

Runtime stages:

`INGEST_WHO → DISCOVER → RETRIEVE → DEDUPE → TRIAGE → EXTRACT → MATCH → SUMMARIZE`

`NEEDS_REVIEW` runtime writes remaining: 0

The dashboard read path retains admin1-centroid, country-centroid, and no-marker
fallback behavior. Fifteen summaries are persisted; 130 newly created events
remain summary-pending because the external summary provider did not complete
within the bounded validation run. The summary stage was the only additional
stage attempted after matching; extraction was not regenerated.

Focused validation:

- `uv run pytest packages/backend/tests/test_lean_mvp_runtime.py packages/backend/tests/test_pipeline_runner.py packages/backend/tests/test_pipeline_fixture.py packages/backend/tests/test_event_read.py -q` — 19 passed
- Targeted `ruff` — passed
- Targeted `mypy` — passed
- `git diff --check` — passed

Branch: `codex/next-iteration`
Commit: see PR head
PR: https://github.com/namwaafetp-commits/EpiSignal/pull/7
Do not merge.
