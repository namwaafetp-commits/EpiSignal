# EpiSignal Event Summary Contract Review

Implementation review completed on branch `codex/next-iteration`.

## 1. Previous contract

The previous event-summary contract did **not** match the requested EpiSignal
flash brief. It used the older `headline`, `summary`, `status`,
`latest_development`, and `uncertainties` shape. The current PR implementation
already replaced that shape with the event-level flash brief; this review adds
the remaining exact-payload and material-change coverage.

## 2. Summary implementation

The current PR implementation changed:

- `packages/backend/src/episignal_backend/events/summarize.py`
- `packages/backend/src/episignal_backend/models/event.py`
- `packages/backend/src/episignal_backend/events/repository.py`
- `packages/backend/src/episignal_backend/events/protocol.py`
- `packages/backend/src/episignal_backend/events/read.py`
- `database/migrations/versions/20260901_0020_event_flash_brief.py`
- the API and generated contract surfaces for event summaries

This review commit additionally changes `summarize.py` and
`test_event_summarize.py`.

The model prompt requests one event summary from all linked observations and
sources. The renderer produces the exact five-part flash brief:

```text
[Pathogen/Disease] Outbreak: [Location] — [Trajectory]
The Snapshot:
[cases] | [deaths / CFR] | [geographic extent]
Key Driver:
[evidence]
Response:
[evidence]
Public/Global Risk:
[evidence]
```

The structured fields are:

```json
{
  "headline": "",
  "trajectory": "Unclear",
  "snapshot": {
    "cases": null,
    "deaths": null,
    "cfr": null,
    "geographic_extent": null
  },
  "key_driver": "",
  "response": "",
  "risk": ""
}
```

All four snapshot keys are now required at the model boundary and remain
nullable, so absent evidence is explicit rather than omitted. Trajectory is
restricted to `Emerging`, `Increasing`, `Stable`, `Declining`, `Contained`,
`Resolved`, or `Unclear`.

## 3. Material-change behavior

Summary generation remains event-level and one-call-per-event. A summary is
generated for a never-summarized event or regenerated only when consolidated
observation material changes. The comparison now includes confirmed, probable,
suspected, total, new, and death counts; CFR; affected-area counts; geographic
extent; and validated material facts. A new article, article count, or summary
age alone does not trigger regeneration. Accepted summaries append a versioned
`event_summaries` row and denormalize the newest brief onto the event.

## 4. Pipeline-order test

`packages/backend/tests/test_pipeline_order_contract.py` verifies the daily
order after ingestion as:

```text
DISCOVER → DEDUP → CLASSIFY → RETRIEVE → EXTRACT → MATCH → SUMMARIZE
```

The event assembly seam covers grouping, observation recording, and the
material-change decision before the event summary stage. With
`relevant=false`, the test proves zero retrieval connector calls, zero
extraction model calls, zero event creation, zero observations, and zero
summary calls.

## 5. Verification

- Backend tests: `1290 passed, 1 skipped, 2 warnings`
- Web tests: `107 passed`
- Formatting: passed
- Lint: passed
- Typecheck: passed; 134 backend/API source files checked
- Contracts: generated and clean
- Production build: passed
- Review commit: `512df17` (`fix: complete event flash brief contract`)

Production was not deployed, merged, migrated, or modified. Production repair
was not executed. The scheduler was not enabled or changed. The earlier
read-only validation confirmed zero production rows changed.
