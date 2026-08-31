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

The 131 eligible historical `NEEDS_REVIEW` rows were requeued directly to
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
within the bounded validation run.

Focused validation:

- `uv run pytest packages/backend/tests/test_lean_mvp_runtime.py packages/backend/tests/test_pipeline_runner.py packages/backend/tests/test_pipeline_fixture.py packages/backend/tests/test_event_read.py -q` — 19 passed
- Targeted `ruff` — passed
- Targeted `mypy` — passed
- `git diff --check` — passed

Branch: `codex/next-iteration`
Commit: recorded in final handoff
PR: not opened; do not merge
