# ADR: Pipeline Funnel v2 (Group-based Cluster Extraction & Relevance Bypass)

* **Status**: Approved
* **Date**: 2026-08-29

## Context and Problem

Previously, the news surveillance pipeline ingested signals, classified each signal for public-health relevance using a cheap LLM call, and then extracted structured epidemiological facts one signal at a time. This approach introduced:
1. **Redundant LLM costs**: Multiple articles representing the same epidemiological event were classified and extracted independently, duplicating token usage and effort.
2. **Ungrounded claims**: Concatenating articles or trying to extract event-level facts across multiple documents without explicit member tracking risked cross-contamination, where text in one article supported a number extracted from another.

We need a system that clusters articles describing the same event, extracts facts from the group as a single unit, and correctly validates the grounding of each claim against the specific document it cited.

## Decision

We implement the **Pipeline Funnel v2** architecture:
1. **Relevance Bypass**: Skip the LLM classification step for individual signals. Since signals are already filtered and grouped into story groups by downstream embedding/rules, relevance is implicitly handled by cluster membership.
2. **Story Group Extraction**: Extract facts from an entire story group as a single cluster using the judgment tier model.
3. **Grounding citations**: Update the extraction schema to Version 3, adding a `source_index` to counts and flags. The model must cite the source index of the specific article from which it extracted each span.
4. **Member-Specific Grounding Verification**: Validate each extracted span specifically against the body of the article it cites, preventing claims from being validated against concatenated text.
5. **Fallback to Single-Signal Extraction**: If a cluster extraction fails or is rejected, the representative signal (member 0) falls back to the standard single-signal extraction ladder, and other deferred duplicates are left open in the story group.

## Consequences

* **Reduced LLM Spend**: Grouping and extracting events as single clusters significantly reduces prompt token overhead.
* **Grounding Rigor**: Grounding verification is strictly enforced per-document, preventing hallucinations and false positives.
* **Robust Failures**: Validation or API failures in cluster runs automatically degrade to single representative runs without losing progress.
