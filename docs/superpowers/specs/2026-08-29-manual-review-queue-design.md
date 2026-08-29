# Manual Review Queue Design

**Date:** 2026-08-29
**Roadmap item:** `M`
**Status:** Approved for implementation planning

## Outcome

Give one authenticated operator a basic internal queue for every signal where
automation refuses to continue. The queue explains why the signal stopped,
shows only the evidence needed to decide, and offers a small set of
cause-specific resolutions. Every resolution is transactional, attributable,
and preserved. A resolved signal either re-enters the existing pipeline at the
earliest safe state, becomes attached to an event through the same event
finalization rules as automation, or is dismissed without deleting evidence.

This implements Phase 1 sections 43 and 44. It does not create accounts, roles,
or a generic workflow engine.

## Why `M` now

`E` is verified, so `M`'s dependency is satisfied. A read-only query against the
live database on 2026-08-29 found 37 signals at `needs_review`:

| Inferred cause | Rows | Evidence used for the inference |
| --- | ---: | --- |
| Event matching could not resolve a canonical disease | 28 | Accepted extraction exists, `disease_id` is null, and no event link exists. |
| Retrieval produced no text | 7 | `raw_text` is null; five are publisher stubs and two are retained test-shaped stubs. |
| Content integrity quarantine | 1 | The known quarantined signal `852aa204-846d-4aa6-a256-82c187fdeaef`. |
| Several candidate events qualified | 1 | A canonical disease and location exist, no event link exists, and the deterministic matcher refused. |

These causes are inferred because the current schema stores only
`processing_status = 'needs_review'`; it does not store the reason. That missing
provenance is part of `M`, not a fact the UI should keep guessing.

Only 3 events existed in the last recorded live proof. Building `G` now would
expose a nearly empty event table. `D2b` could improve one ambiguous match and
`F` could improve model selection, but neither gives a human a path through the
36 other review rows. `M` closes an already-open production loop before opening
another surface or optimization project.

## Approaches considered

### Chosen: durable review cases plus cause-specific resolutions

Store why review began, candidate-event scores when relevant, and the eventual
resolution. Query open cases rather than inferring a queue from signal columns.
Put resolution behavior behind one backend interface and reuse event
finalization for event mutations.

This adds a migration and a small review module, but it gives reliable
provenance, race-safe writes, and a queue that can distinguish recovery paths.

### Rejected: infer everything from the signal row

This is smaller initially: list `needs_review` signals and branch on null fields.
It cannot distinguish all writers, cannot preserve the candidate set that caused
a refusal, and cannot explain historical decisions. A future state change could
silently rewrite the apparent reason for an old review.

### Rejected: generic review-workflow engine

A generic state machine with configurable steps, assignees, comments, and
permissions would support later operations work. Phase 1 has one operator, one
queue, and six resolutions. The extra interface would be wider than the
behavior it hides.

## Vocabulary and invariants

`CONTEXT.md` defines **review case**, **resolution**, and **dismissal**.

The load-bearing invariants are:

1. Every new transition to `needs_review` opens or reuses one open review case
   with a typed reason. No writer sets the status without recording the reason.
2. A signal has at most one open review case. It may accumulate closed cases
   over time.
3. A resolution never deletes or overwrites signal text, extraction, AI cost
   rows, event observations, or earlier review history.
4. A human may choose a disease or event, but may not edit extracted facts or
   source text in this item.
5. Event linking and creation write the same event signal, observations,
   locations, scores, and verification status as deterministic assembly.
6. Dismissal preserves the signal and moves it to a terminal processing status;
   no automated stage selects it.
7. Queue responses never expose `raw_text`, model prompts, credentials,
   exception messages, or patient-level data.
8. Every admin review endpoint requires one server-configured bearer token.
   Tokens are compared in constant time and are never persisted in the browser.

## Data model

### Controlled vocabularies

Add these values under `packages/backend/src/episignal_backend/db/types.py`:

```python
class ReviewReason(StrEnum):
    RETRIEVAL_FAILED = "retrieval_failed"
    EXTRACTION_REJECTED = "extraction_rejected"
    DISEASE_UNRESOLVED = "disease_unresolved"
    EVENT_MATCH_AMBIGUOUS = "event_match_ambiguous"
    CONTENT_INTEGRITY = "content_integrity"
    LEGACY_UNCLASSIFIED = "legacy_unclassified"


class ReviewStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ReviewResolution(StrEnum):
    RETRY_RETRIEVAL = "retry_retrieval"
    RETRY_EXTRACTION = "retry_extraction"
    ASSIGN_DISEASE = "assign_disease"
    LINK_EVENT = "link_event"
    CREATE_EVENT = "create_event"
    DISMISS = "dismiss"
    RECOVERED_AUTOMATICALLY = "recovered_automatically"
```

Add `DISMISSED = "dismissed"` to `ProcessingStatus`. `dismissed` is a terminal
human outcome, distinct from `failed`, `duplicate`, and `needs_review`.

### `signal_review_cases`

One row records one review episode:

| Column | Shape | Rule |
| --- | --- | --- |
| `id` | UUID primary key | Stable case identifier. |
| `signal_id` | UUID FK to `signals`, restricted delete | Evidence cannot disappear beneath audit history. |
| `reason` | `ReviewReason` | Required at open time. |
| `status` | `ReviewStatus` | Starts `open`; changes once to `resolved`. |
| `opened_at` | timezone-aware timestamp | Required. |
| `resolved_at` | nullable timezone-aware timestamp | Required exactly when resolved. |
| `resolution` | nullable `ReviewResolution` | Required exactly when resolved. |
| `reviewed_by` | nullable text, max 120 characters | Required for human resolutions; null only for automatic recovery. |
| `note` | nullable text, max 1000 characters | Operator explanation; whitespace-only values rejected. |
| `selected_disease_id` | nullable FK to `diseases`, restricted delete | Present only for `assign_disease`. |
| `selected_event_id` | nullable FK to `events`, restricted delete | Present for `link_event` and the event created by `create_event`. |
| `created_at`, `updated_at` | timestamps | Repository-standard audit fields. |

A partial unique index on `signal_id WHERE status = 'open'` enforces one open
case per signal. Check constraints enforce the resolution/timestamp pairing and
the allowed target columns for each resolution.

### `signal_review_candidates`

This table preserves the event set that caused an ambiguous decision:

| Column | Shape | Rule |
| --- | --- | --- |
| `review_case_id` | UUID FK, cascade delete | Part of composite primary key. |
| `event_id` | UUID FK, restricted delete | Part of composite primary key. |
| `match_score` | float in `0..1` | Exact deterministic score at refusal time. |
| `created_at` | timestamp | Snapshot time. |

Candidate rows are evidence for the decision, not live search results. The
resolution interface may link only one of the stored candidates. If the
operator wants a different event, the safe choices in Phase 1 are create a new
event or leave the case open.

## Migration and compatibility

Create Alembic revision `20260829_0010_manual_review_cases` after `0009`.

Forward order:

1. Expand the processing-status constraint with `dismissed`.
2. Create review vocabularies, tables, constraints, and indexes.
3. Backfill one open case for every signal currently at `needs_review`.
4. Verify every such signal has exactly one open case before the migration
   commits.

Backfill classification is conservative and ordered:

1. Known quarantine IDs become `content_integrity`.
2. Null or blank `raw_text` becomes `retrieval_failed`.
3. Missing extraction after rejected AI attempts becomes
   `extraction_rejected`.
4. Accepted extraction with null `disease_id` becomes `disease_unresolved`.
5. A disease plus two or more qualifying candidate events becomes
   `event_match_ambiguous`, with candidate snapshots written.
6. Anything not proven by those predicates becomes `legacy_unclassified`.

The migration never rewrites signal content or moves a signal out of review.
Backfill inserts are idempotent against the partial unique index.

The current deployment is one Python process plus a scheduler, so there is no
required mixed-version overlap. Migration runbook: stop the scheduler, migrate,
deploy backend and web together, run schema and live queue checks, then restart
the scheduler. Older code remains safe during the expand step because it never
writes `dismissed`; it must not run after the new app begins writing resolutions.

Downgrade is reversible only before review data exists. On an empty review
schema it drops the two tables and contracts the processing-status constraint.
If any case or dismissed signal exists, downgrade aborts with explicit guidance
rather than deleting audit history. Recovery after live use is forward-only or
from a database backup.

## Backend modules and interfaces

Create `packages/backend/src/episignal_backend/review/` with four focused files:

- `documents.py`: frozen command and response types plus the action/reason
  compatibility table.
- `protocol.py`: the narrow `ReviewRepository` interface used by resolution
  behavior and tests.
- `resolve.py`: pure orchestration of one resolution transaction; imports no
  SQLAlchemy or HTTP library.
- `repository.py`: SQLAlchemy query, row lock, persistence, and transaction
  adapter.

The public backend interface is deliberately small:

```python
def query_review_queue(
    session: Session, *, limit: int = 50, offset: int = 0
) -> ReviewQueuePage: ...

def resolve_review_case(
    repo: ReviewRepository, command: ResolveReviewCommand
) -> ReviewCaseResult: ...
```

Callers do not learn how cases, candidates, events, or status transitions are
stored. Tests exercise the same resolution interface used by the API.

### Opening and automatically closing cases

Replace every bare `mark_needs_review(signal_id)` call with a typed operation:

```python
repo.open_review(signal_id, reason=ReviewReason.EXTRACTION_REJECTED)
```

Event refusal also passes its `candidate_scores`. Missing-disease refusal uses
`DISEASE_UNRESOLVED`. Discovery opens `RETRIEVAL_FAILED`. The integrity backfill
uses `CONTENT_INTEGRITY`.

If a later automatic retrieval succeeds while its case remains open, promotion
closes that case as `RECOVERED_AUTOMATICALLY`. No human identity is fabricated.

### Event finalization reuse

Extract the existing attach/create loops from `events/assemble.py` into
`events/finalize.py`. Both automated assembly and manual resolution call that
module. It owns:

- event-signal attachment and relationship type;
- observation and location writes;
- signal transition to `matched`;
- early-signal and evidence score recomputation;
- verification-status recomputation.

This is an internal module, not a new external seam. Its deletion test is
strong: without it, identical correctness rules would reappear in automated and
manual callers.

## Resolution behavior

The repository locks the open case row with `SELECT ... FOR UPDATE`. A second
resolution attempt after the first returns `409 REVIEW_ALREADY_RESOLVED` and
does not repeat mutations.

| Review reason | Allowed resolution | Result |
| --- | --- | --- |
| `retrieval_failed` | `retry_retrieval` | Reset retrieval attempts, close the case, keep the signal selectable by the existing retry pass; success later advances it normally. |
| `retrieval_failed` | `dismiss` | Close case and set signal to `dismissed`. |
| `extraction_rejected` | `retry_extraction` | Close case and set signal to `classified`; the extraction pass selects it. |
| `extraction_rejected` | `dismiss` | Close case and set signal to `dismissed`. |
| `disease_unresolved` | `assign_disease` | Set canonical `disease_id`, close case, and set signal to `geocoded`; event assembly selects it. |
| `disease_unresolved` | `dismiss` | Close case and set signal to `dismissed`. |
| `event_match_ambiguous` | `link_event` | Require a stored candidate, finalize attachment, close case, and leave signal `matched`. |
| `event_match_ambiguous` | `create_event` | Create and finalize one event from the signal, close case, and leave signal `matched`. |
| `event_match_ambiguous` | `dismiss` | Close case and set signal to `dismissed`. |
| `content_integrity` | `dismiss` | Close case and set signal to `dismissed`; no corrupt content is reintroduced. |
| `legacy_unclassified` | `dismiss` | Close case and set signal to `dismissed`. |

`retry_retrieval` keeps the underlying processing status at `needs_review`
because the existing retry selector uses that state. The queue itself reads
open review cases, so closing the case removes it from human work while the
automated retry owns the signal. A subsequent exhausted failure opens a new
case rather than reopening history.

Every command requires `reviewed_by`. `note` is required for `dismiss` and
optional otherwise. The backend ignores no incompatible or extra fields; the
command is a discriminated union with `extra = 'forbid'`.

## Admin authentication

Add optional secret setting `EPISIGNAL_ADMIN_TOKEN`. Application startup stays
possible without it so public reads and tests still work. Review endpoints then
return `503 ADMIN_REVIEW_DISABLED` until it is configured.

Requests use:

```http
Authorization: Bearer <token>
```

Missing or wrong tokens return the same `401` body and `WWW-Authenticate:
Bearer`. Comparison uses `secrets.compare_digest`. Logs may record request ID,
case ID, action, and outcome, but never the header or token. CORS expands only
from `GET` to `GET, POST` for already-allowed origins.

The web UI asks the operator for the token in a password input and keeps it only
in component memory. It is not placed in a URL, cookie, local storage, server
rendered HTML, or any `NEXT_PUBLIC_` variable.

## HTTP interface

### `GET /api/v1/admin/reviews`

Query parameters: `limit` (`1..50`, default `50`) and `offset` (`>=0`, default
`0`). Phase 1 returns open cases only, oldest first, then UUID for stable order.

Each item contains:

- case ID, reason, and opened time;
- signal ID, English title when valid, original title otherwise, source name,
  source URL, first-seen time, and retrieval attempts;
- extracted disease text and canonical disease when present;
- recorded signal locations with role, precision, and label, but no fabricated
  coordinates for unresolved places;
- stored candidate events with public ID, title, verification status, and match
  score;
- allowed resolutions for that reason.

The page also contains canonical disease options (`id`, `canonical_name`) so a
missing-disease case can be resolved without another endpoint. It never returns
raw text, full extraction JSON, source spans, prompts, AI request bodies,
exception text, or credentials.

### `POST /api/v1/admin/reviews/{case_id}/resolve`

Accepts the discriminated resolution command plus `reviewed_by` and optional
`note`. Success returns the closed case ID, resolution, resulting processing
status, selected disease or event ID when applicable, and `resolved_at`.

Errors use stable codes:

- `401 ADMIN_AUTH_REQUIRED`
- `404 REVIEW_CASE_NOT_FOUND`
- `409 REVIEW_ALREADY_RESOLVED`
- `409 REVIEW_ACTION_NOT_ALLOWED`
- `409 REVIEW_TARGET_STALE`
- `422` for malformed contracts
- `503 ADMIN_REVIEW_DISABLED`

Wrong-state and wrong-target failures leave both case and signal unchanged.

## Web interface

Add `/admin/reviews` beside the existing read-only pipeline monitor. It is a
small client-rendered internal screen:

1. Locked state asks for admin token and operator name.
2. Successful authentication loads oldest open cases.
3. Each case card shows reason in plain language, signal/source facts, AI
   disease, locations, and candidate events with scores when present.
4. Only allowed actions render. Disease and event choices use native labelled
   controls. Destructive dismissal requires a note and explicit confirmation.
5. A successful resolution removes the card and announces the result through
   an `aria-live` region. A failed action preserves the card and inputs.
6. Empty, loading, unauthorized, disabled, and unavailable states are distinct.

No raw text editor, extraction editor, event search, batch action, assignment,
pagination controls beyond a simple next/previous pair, or visual redesign is
included.

## Error handling and concurrency

- Queue reads skip malformed stored extraction fields and show the remaining
  safe facts; they never fail the whole page because one legacy payload is bad.
- Candidate snapshots are authoritative for `link_event`. A deleted or no
  longer valid target produces `REVIEW_TARGET_STALE` without mutation.
- Resolution is one database transaction. Any event-finalization failure rolls
  back case, signal, event, observation, location, and score writes together.
- Automatic writers use the same partial unique index, so retries cannot open
  duplicate cases.
- A resolution request never runs model or external publisher calls inline.

## Test seams and proof

These are the agreed public seams for worker tests:

1. Migration up/down on an empty database, plus forward backfill against
   representative legacy rows and refusal to downgrade after live review data.
2. `open_review` and automatic recovery through repository interfaces,
   including the one-open-case invariant.
3. `resolve_review_case` through a hand-written `ReviewRepository` fake for
   every allowed and forbidden reason/action pair, rollback, and duplicate
   resolution.
4. Existing `run_event_assembly` plus manual link/create behavior, proving both
   routes produce the same durable event effects.
5. FastAPI endpoints through dependency overrides, including auth, exact JSON
   shapes, bounded queries, stable error codes, and forbidden-field scans.
6. Web response validation using independent malformed fixtures.
7. Review component behavior through accessible labels and user events,
   including token handling, reason-specific controls, success removal, and
   preserved state on failure.
8. Contract generation parity, production build, database migration check, and
   full `corepack pnpm verify`.

## Acceptance

`M` is complete when:

1. Every signal newly sent to `needs_review` has one typed open review case.
2. Existing live review rows are backfilled without changing signal content or
   status, and the observed total reconciles exactly before and after migration.
3. An authenticated operator can see title, source, AI disease, locations,
   candidate events, and match scores when those facts exist.
4. Retrieval, extraction, disease, ambiguous-event, integrity, and legacy cases
   expose only their allowed resolutions.
5. Retry and disease assignment re-enter the existing automated pipeline at the
   earliest safe status.
6. Manual event linking and creation preserve the same provenance,
   observations, locations, scores, and verification rules as automation.
7. Dismissal is terminal but preserves signal and review history.
8. Concurrent or repeated resolution cannot apply side effects twice.
9. Missing, wrong, or unconfigured admin credentials cannot read or mutate the
   queue, and no secret reaches logs or persisted browser storage.
10. `corepack pnpm verify` exits 0; the completion report quotes real Python and
    web test counts, contract parity, and production-build output.
11. Live proof records the pre-migration reason composition, post-migration case
    counts, one safe non-destructive resolution, and database health. Do not
    dismiss or relink live evidence solely to create proof.

## Out of scope

- Accounts, roles, sessions, password recovery, or public registration.
- Editing raw source text, extraction facts, source spans, locations, or event
  observations.
- Arbitrary event search or linking outside stored candidates.
- Batch resolution, assignment, comments, SLA timers, notifications, or alerts.
- Reprocessing corrupt content automatically.
- Deleting signals, review cases, AI cost rows, events, or observations.
- `D2b` embeddings or model-assisted candidate decisions.
- Public event API work from `G` or event-page work from `H` and `I`.
