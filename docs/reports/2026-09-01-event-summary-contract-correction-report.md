# EpiSignal Event Summary Contract and Pipeline Order Correction

The previous event-summary contract did not match the newly agreed EpiSignal
flash brief. It returned the older `headline`, `summary`, `status`,
`latest_development`, and `uncertainties` shape. This correction makes the
summary event-level, structured, versioned, and rendered in the five-part
flash-brief format.

The structured summary fields are:

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

`trajectory` is restricted to `Emerging`, `Increasing`, `Stable`,
`Declining`, `Contained`, `Resolved`, and `Unclear`. The renderer produces the
headline, `The Snapshot:`, `Key Driver:`, `Response:`, and
`Public/Global Risk:` sections. The summarizer receives every linked source
and consolidated observation, prefers the newest credible figures, preserves
confirmed/suspected/probable distinctions and conflicts, and uses the allowed
fallbacks when evidence is missing.

Summary generation is gated to a never-summarized event or a material change
in consolidated observations: counts, deaths, CFR, geographic extent,
pathogen, transmission, response, or trajectory. A new source, article count,
or summary age alone does not trigger regeneration. Existing summary rows are
retained as version history, while the latest rendered brief is denormalized
onto the event.

The scheduled chain is now explicitly ordered as `DISCOVER`, metadata-only
`DEDUP`, `CLASSIFY`, `RETRIEVE`, `EXTRACT` (including extraction validation),
event grouping/matching with observation recording, and event-level summary.
An explicit irrelevant classification is terminal: it causes no retrieval,
extraction, event creation, or summary call. Metadata-only deduplication uses
canonical URL, normalized title, and near-exact title checks before retrieval;
body-aware deduplication remains available for paths that have article text.

The correction adds exact flash-brief tests, grouped-observation prompt tests,
material-change tests, structured persistence/API tests, and a pipeline-order
test covering the irrelevant stop. Migration
`20260901_0020_event_flash_brief.py` adds the structured summary columns and
trajectory constraint without removing historical rows.

Production deployment, repair, merge, and scheduler enablement were not
performed.
