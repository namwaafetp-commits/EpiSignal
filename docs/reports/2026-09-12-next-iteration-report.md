# Next iteration — focused surveillance and two-level grouping

**Date:** 2026-09-12  
**Branch:** `codex/next-iteration`  
**Production HEAD at start:** `d6e63af`

## ARCHITECTURE

Before: `DISCOVER → DEDUPE → CLASSIFY → RETRIEVE → EXTRACT → MATCH → SUMMARIZE`.

After: `DISCOVER → DEDUPE → CLASSIFY → RETRIEVE → STORY_GROUP → EXTRACT → MATCH → SUMMARIZE`.

Retrieval remains before story grouping because grouping uses retrieved article
text; relevance still gates retrieval. Story grouping is distinct from article
dedupe and strict epidemiologic event matching.

## ARTICLE DEDUPE

Current behavior: existing exact and near-exact article deduplication remains
the first post-discovery content decision.

Changed: **NO**. Story grouping does not replace article dedupe.

## STORY GROUPING

Implementation: `ingestion/story.py` provides immutable deterministic story
groups. The scheduler computes groups for the event-match batch and passes stable
IDs into assembly; direct assembly uses the same seam.

Evidence used: normalized token-set title similarity, token-set body similarity,
distinctive-term overlap, and publication/first-seen proximity.

Threshold/decision logic: approximately 35% title, 35% body, 20% distinctive
terms, and 10% time. A match needs score `0.72`, or the conservative strong
entity exception (at least four shared distinctive terms, title similarity at
least `0.45`, body similarity at least `0.45`). All group members must agree;
the story window is 48 hours.

Missing-location behavior: location is not used by story grouping. Unresolved
signals can join a strong same-story group. Event assembly aggregates resolved
disease/location evidence from any member for strict clustering; otherwise an
uncertain story unit remains separate.

Disease-disagreement behavior: disease identity does not reject a strong
same-story group. Strict epidemiologic matching remains disease-compatible after
story grouping.

False-merge safeguards: generic terms alone never match; same disease/country/
day and discovery rule are not positive evidence; weak similarity, different
locations, and updates outside the story window remain separate. Overlapping
caller-supplied IDs are de-duplicated before attachment.

## ANTHROPIC FIXTURE

Articles: **4** strongly similar reports with unresolved epidemiologic identity.

Story clusters: **1**.

Relevant/irrelevant result: the relevance prompt classifies the Anthropic AI
biological-weapons report as **irrelevant**, even when pathogen names appear.

Events created: **1** uncertain event if the fixture reaches assembly.

Supporting signals: **4** remain attached to that event.

## EVENT GROUPING

Existing matcher changes: none to disease, location, time, event-history, or
candidate scoring compatibility.

Threshold changes: **NONE**. Existing match, review, distance, and cluster
distance values are unchanged.

`review_threshold` wiring: scheduled production assembly continues to pass
`review_threshold=None` because Lean MVP policy creates a new event for
ambiguous/incomplete decisions instead of opening a review case or waiting for
a judge. The configured value remains available to direct callers and tests.

Unresolved-location behavior: strong same-story articles are one unit; other
unresolved story units remain separate rather than being automatically merged.

## DEEPSEEK RELEVANCE

Old definition: broad public-health relevance, including general programs and
system issues.

New definition: a real infectious-disease event affecting humans and/or animals
that is reported, updated, investigated, confirmed, suspected, or actively
responded to. Disease-name presence alone is insufficient; ruled-out disease is
not a positive event.

Anthropic result: **irrelevant** by the updated classifier instructions.

Ruled-out disease result: a passenger later confirmed not to have Ebola is not
an Ebola event.

## GEMINI

Model: `google/gemini-3.1-flash-lite`.

Fields: disease, locations, optional categories, and controlled optional tags.

Tags: outbreak, cluster, human/animal cases, zoonotic, death,
hospitalization, cross-border, surveillance, vaccination, control measure,
foodborne, waterborne, vector-borne, healthcare-associated, antimicrobial
resistance, and unknown pathogen.

Prose summary: **NO**. Recommendations, interpretation, and invented tags are
excluded by the prompt and contract.

## SUMMARY

Old model: `mistralai/mistral-small-3.2-24b-instruct`.

New model: `deepseek/deepseek-v4-flash-0731`, through existing OpenRouter
routing.

Old schema: `title`, `bullets`, and required `takeaway`.

New schema: `title` and `bullets`; `takeaway` is optional for legacy
readability.

Bullet rules: 3–5 non-blank, fact-grounded bullets with no mandatory takeaway
or fixed epidemiologic fields.

Word rules: approximately 30–100 words across all bullets; payloads outside the
range are rejected.

Legacy compatibility: historical structured summaries and existing frontend
payloads with `takeaway` continue to render; new payloads omit it when absent.

## REGRESSION TESTS

Same story unresolved: **PASS** — four Anthropic variants form one story.

Same story disease disagreement: **PASS**.

Same disease distinct outbreaks: **PASS** — Province A and Province B remain
separate.

Same disease unresolved unrelated: **PASS**.

Different disease unrelated: **PASS**.

Weak similarity: **PASS**.

Multiple publishers same report: **PASS** — one story with three supporting
signals.

Different updates same outbreak: **PASS** — separate stories; strict event
grouping can still assemble the same disease/location event.

Relevance tests: **PASS** — prompt/validation coverage for active events,
disease-name insufficiency, Anthropic misuse reporting, and ruled-out disease.

Gemini tests: **PASS** — identity fields, categories/tags, controlled tags,
missing fields, and no prose contract.

Summary tests: **PASS** — DeepSeek route, 3/4/5 bullets, invalid counts, word
budget, uncertainty/source grounding, and optional legacy takeaway rendering.

## VERIFY

Full `corepack pnpm verify` at final HEAD
`d9bb2ea1908df694228908382761ec8fbb531a5a`:

```text
format: PASS — Ruff 317 files formatted; Prettier all matched files.
lint: PASS — Ruff and ESLint.
typecheck: PASS — web tsc; mypy no issues in 149 source files.
Python: PASS — 1,518 passed, 2 skipped, 2 existing deprecation warnings.
Web: PASS — 125 tests passed in 15 files.
contracts: PASS — OpenAPI generated and contract diff clean.
build: PASS — Next.js production build completed successfully.
Alembic: 20260911_0024 (head).
```

No unexpected xfail occurred. The two warnings are the existing Starlette/
httpx and anyio deprecations.

## GIT

Previous HEAD: `d6e63af`  
New HEAD: `d9bb2ea`  
Remote HEAD before push: `d6e63af`  
Working tree: clean before this report commit.

## PRODUCTION

Deployed: **NO**  
Production DB changed: **NO**  
VPS accessed: **NO**  
Coolify accessed: **NO**
