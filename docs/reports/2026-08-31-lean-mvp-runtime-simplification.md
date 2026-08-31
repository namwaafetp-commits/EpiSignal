# Lean MVP runtime and recovery report

Date: 2026-08-31

## Runtime and recovery baseline

Before events: 14

Before summaries: 14

Backlog extracted: 131

After events: 145

After summaries: 15

Attached existing: 0

Created new: 131

Unmapped before: 130

Remaining blocked: 41

Historical review rows examined: 172

Valid extracted backlog: 131

Invalid extractions: 41

Requeued: 131

New events: 131

Attached existing: 0

The 131 valid rows were requeued directly to `EXTRACTED` and processed only
through `MATCH → SUMMARIZE`. The 41 remaining `NEEDS_REVIEW` rows have invalid
stored extractions. No discovery, retrieval, dedupe, triage, or extraction was
rerun.

## PR #7 clarification

Country normalization fixed: YES

Extraction country resolution is exact and non-geocoded. A valid triage ISO-2
value wins; otherwise the existing country alias/GDELT country-name helpers are
used; otherwise the country is null. Focused coverage includes Thailand → TH,
United States → US, and an unknown country → null.

Recovery events currently: 145

Potential duplicate event groups: 2

Recommended resulting event count after safe consolidation: 143

Unmapped before: 130

Unmapped after country normalization: 101

The duplicate audit was read-only. It found two exact normalized
disease-identity + country groups within the seven-day matching window; no
events were merged in this patch.

Summaries persisted: 15

Summaries remaining: 130

Summary per-completion commit: YES

Exact pending reason: the summary provider was configured and 15 requests
completed successfully. The remaining 130 model calls were launched by the
bounded validation run but did not complete before that run was stopped; the
old batch implementation only wrote request/summary rows after a whole batch
returned. They were not skipped intentionally, and the available evidence does
not indicate a missing key, request/cost guard, rate limit, or unavailable
model. No full-pipeline rerun or extraction regeneration was performed.

Invalid extraction explanation: all 172 historical `NEEDS_REVIEW` rows were
examined; 131 had valid stored extractions and were requeued, while 41 could
not be parsed and remained blocked. The 131 new events were created because
the earlier recovery matching pass treated each eligible unresolved-disease
row as a standalone event. This patch adds exact disease-text fallback
identity and candidate-event fallback lookup, so future matching can attach
same disease + country + time without embeddings, fuzzy matching, an LLM judge,
or human review. The two potential duplicate groups above are the safe
read-only consolidation candidates among the existing recovery events.

## Runtime

Runtime stages:

`INGEST_WHO → DISCOVER → RETRIEVE → DEDUPE → TRIAGE → EXTRACT → MATCH → SUMMARIZE`

`NEEDS_REVIEW` runtime writes remaining: 0

Event creation is never blocked by unresolved disease or country. The dashboard
location fallback remains admin1 centroid, then country centroid, then no
marker. No `GEOCODE`, `PREGROUP`, `ECDC`, embeddings, or normal-path event judge
stage is in the runtime chain.

Focused tests: 26 passed

Targeted ruff: passed

Targeted mypy: passed

`git diff --check`: passed

Branch: `codex/next-iteration`

Commit: see PR head

PR: https://github.com/namwaafetp-commits/EpiSignal/pull/7

Do not merge.

## Recovery reconciliation

Safety assertions passed before mutation: 131 recovery signals,
131 recovery-created events, and 14 baseline events. Only those 131 recovery
event artifacts were removed; the 14 baseline events were preserved. The 131
recovery signals were reset to `EXTRACTED`.

MATCH ran only for the recovery set in two batches:

- Batch 1: examined 100, attached existing 100, created 95 events.
- Batch 2: examined 31, attached existing 31, created 30 events.

All 131 recovery signals were processed. Eight recovery signals are grouped
across two multi-signal recovery events. Zero recovery signals attached to a
baseline event.

SUMMARIZE ran only after MATCH completed. Two SUMMARIZE-only runs processed 100
and 25 events. All 125 recovery summaries were accepted and persisted; no
failure or unavailable result occurred. Live read-only checks observed
per-completion persistence while the first run was still active.

Final persisted verification:

- Baseline events preserved: 14/14
- Recovery signals processed: 131
- Attached to baseline events: 0
- Recovery signals grouped together: 8 signals across 2 events
- New recovery events: 125
- Total events: 139
- Mapped: 38
- Admin1: 21
- Country: 17
- Unmapped: 101
- Summaries: 139
- Unsummarized events: 0
- Dashboard events: 139
- Potential duplicate groups remaining: 2, both baseline-only; recovery-only 0

GDELT run: NO

Extraction rerun: NO

Full pipeline run: NO

Reset/requeue repeated: NO
