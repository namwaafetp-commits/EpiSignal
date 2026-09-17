# Event identity reconciliation — completion report

**Date:** 2026-09-12  
**Branch:** `codex/next-iteration`  
**Implementation commit:** `577dbcb`

## ROOT CAUSE

Previous disease representative behavior selected the first available
`disease_id`, so story ordering could decide disease identity. Previous
location representative behavior unioned every member location, allowing one
bad extraction to make a story match any of its locations. The false-merge
scenario was a story reporting Bangkok three times and Singapore once becoming
eligible for an unrelated Singapore event.

## FIX

Disease reconciliation counts non-placeholder resolved identities. A single
identity, a strict consensus, or one resolved identity among unresolved peers
is used. Ties and unresolved conflicts produce no disease identity. Generic,
unknown, and unspecified placeholder text is treated as unresolved.

Location reconciliation keeps only exact resolved location identity evidence.
All agreeing evidence selects one location, preferring a primary role and
higher precision. One resolved location can represent unresolved peers. Any
conflicting resolved locations produce no epidemiologic representative
location; no fuzzy geography or majority winner is used.

The reconciled representative is carried through expanded `StoryCluster`
objects so final event matching and creation use it while all original signals
remain attached and their source evidence remains available. Story grouping
terminology now says `distinctive-term overlap`; it does not claim NER.

## TESTS

| Case | Result |
| --- | --- |
| one bad location, 3 Bangkok / 1 Singapore | PASS — representative location unresolved; unrelated Singapore event not attached |
| one location + unresolved peers | PASS — Bangkok attaches to existing Bangkok event |
| 2-vs-2 conflicting locations | PASS — location unresolved |
| disease consensus, 3 resolved / 1 generic or unknown | PASS — resolved disease retained |
| conflicting disease, 2-vs-2 | PASS — disease unresolved |
| existing Anthropic fixture | PASS — 4 articles remain 1 story group and relevance rejects it |
| existing event matching and resolved story tests | PASS |

## VERIFY

`corepack pnpm verify` at `577dbcb`:

```text
format: PASS — Ruff 317 files already formatted; Prettier all matched files.
lint: PASS — ESLint and Ruff checks passed.
typecheck: PASS — web tsc; mypy no issues in 149 source files.
Python: PASS — 1,523 passed, 2 skipped, 2 existing deprecation warnings.
Web: PASS — 125 tests passed in 15 files.
contracts: PASS — OpenAPI generated and contract diff clean.
build: PASS — Next.js production build completed successfully.
Alembic: 20260911_0024 (head).
```

Focused changed-domain tests: 70 passed. Fixed-point review found no
standards or scope findings.

## GIT

Previous HEAD: `c8f2ce9`  
New HEAD: `577dbcb` before this completion report commit  
Remote HEAD before push: `c8f2ce9`  
Working tree: clean after the completion report commit

## PRODUCTION

Deployed: **NO**  
Production DB changed: **NO**  
VPS accessed: **NO**  
Coolify accessed: **NO**
