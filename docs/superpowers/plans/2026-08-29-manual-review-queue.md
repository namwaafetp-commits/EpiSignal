# Manual Review Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give an authenticated operator a durable queue of signals that need human review and safe, attributable resolutions back into the existing pipeline or into terminal dismissal.

**Architecture:** Add review-case and candidate-snapshot tables behind a small `review` module. Every writer opens a typed case when it moves a signal to `needs_review`; one transactional resolver validates cause-specific commands and reuses extracted event-finalization behavior. FastAPI exposes bearer-protected list and resolve endpoints. A client-rendered Next page strictly validates responses while keeping the token only in memory and adapts the supplied surveillance-console cues inside the existing web shell.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL/PostGIS, FastAPI, Next.js 16 App Router, React 19, TypeScript, Vitest, Testing Library, pnpm, uv.

---

## Required reading and fixed seams

Read before Task 1:

- `AGENTS.md`, `STATUS.md`, `HANDOFF.md`, and `docs/agents/workflow.md`
- `CONTEXT.md`
- `docs/superpowers/specs/2026-08-29-manual-review-queue-design.md`
- `.agents/skills/lean-build/SKILL.md`, `.agents/skills/tdd/SKILL.md`, and `.agents/skills/migration/SKILL.md`

Before any Next.js edit, follow `apps/web/AGENTS.md` and read the applicable
installed Next.js guides under `apps/web/node_modules/next/dist/docs/`.

Tests are agreed at these public seams:

1. Alembic upgrade/downgrade and data backfill.
2. `ReviewRepository` plus `open_review`/automatic recovery.
3. `resolve_review_case(repo, command)` through a hand-written fake.
4. Automated and manual event finalization through their public functions.
5. FastAPI list/resolve endpoints through dependency overrides.
6. `isReviewQueuePage`, `getReviewQueue`, and `resolveReview` in the web client.
7. `AdminReviewQueue` through accessible user behavior.

Do not add tests against private helpers or SQLAlchemy implementation details
outside the migration/model contract tests.

## File map

Create:

- `packages/backend/src/episignal_backend/models/review.py` — review ORM rows.
- `packages/backend/src/episignal_backend/review/__init__.py` — package exports.
- `packages/backend/src/episignal_backend/review/documents.py` — frozen commands and read models.
- `packages/backend/src/episignal_backend/review/protocol.py` — narrow storage interface.
- `packages/backend/src/episignal_backend/review/resolve.py` — resolution orchestration.
- `packages/backend/src/episignal_backend/review/repository.py` — SQLAlchemy adapter and queue query.
- `packages/backend/src/episignal_backend/events/finalize.py` — shared event mutation rules.
- `database/migrations/versions/20260829_0010_manual_review_cases.py` — expand/backfill/guarded rollback.
- `packages/backend/tests/test_review_documents.py`
- `packages/backend/tests/test_review_protocol.py`
- `packages/backend/tests/test_review_repository.py`
- `packages/backend/tests/test_review_resolve.py`
- `packages/backend/tests/test_event_finalize.py`
- `apps/api/src/episignal_api/routes/reviews.py`
- `apps/api/tests/test_reviews.py`
- `apps/web/src/lib/api-reviews.ts`
- `apps/web/src/lib/api-reviews.test.ts`
- `apps/web/src/components/admin-review-queue.tsx`
- `apps/web/src/components/admin-review-queue.test.tsx`
- `apps/web/src/app/admin/reviews/page.tsx`

Modify only where named by a task:

- vocabularies/models: `db/types.py`, `models/__init__.py`, model and schema tests;
- existing review writers: discovery, AI, event assembly, their protocols,
  repositories, tests, and migration `0009` compatibility proof;
- app composition/config: `config.py`, API dependencies/factory, env examples;
- generated contracts, homepage navigation, `STATUS.md`, `ROADMAP.md`, and the
  completion report during final gate work.

## Task 1: Define review vocabularies and ORM shape

**Files:**

- Create: `packages/backend/src/episignal_backend/models/review.py`
- Modify: `packages/backend/src/episignal_backend/db/types.py`
- Modify: `packages/backend/src/episignal_backend/models/__init__.py`
- Modify: `packages/backend/tests/test_models.py`
- Create: `packages/backend/tests/test_review_documents.py`

- [ ] **Step 1: Write failing vocabulary and metadata tests**

Add assertions for exact values and table shape:

```python
def test_review_vocabularies_are_closed() -> None:
    assert {value.value for value in ReviewReason} == {
        "retrieval_failed", "extraction_rejected", "disease_unresolved",
        "location_unresolved", "event_match_ambiguous", "content_integrity",
        "legacy_unclassified",
    }
    assert {value.value for value in ReviewStatus} == {"open", "resolved"}
    assert ReviewResolution.DISMISS == "dismiss"
    assert ProcessingStatus.DISMISSED == "dismissed"


def test_review_tables_preserve_signal_and_candidate_provenance() -> None:
    case = Base.metadata.tables["signal_review_cases"]
    candidate = Base.metadata.tables["signal_review_candidates"]
    assert next(iter(case.c.signal_id.foreign_keys)).ondelete == "RESTRICT"
    assert [column.name for column in candidate.primary_key] == [
        "review_case_id", "event_id"
    ]
```

Update `EXPECTED_TABLES` with both table names and update the persisted-enum
column count from `19` to `22`.

- [ ] **Step 2: Run the focused tests and confirm red**

Run:

```powershell
uv run pytest packages/backend/tests/test_models.py packages/backend/tests/test_review_documents.py -q
```

Expected: collection/import failure for missing review vocabularies or models.

- [ ] **Step 3: Add exact vocabularies and models**

Add the enum values from the design. Model the case constraints explicitly:

```python
class SignalReviewCase(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "signal_review_cases"
    __table_args__ = (
        CheckConstraint(
            "(status = 'open' AND resolution IS NULL AND resolved_at IS NULL) OR "
            "(status = 'resolved' AND resolution IS NOT NULL AND resolved_at IS NOT NULL)",
            name="review_resolution_state",
        ),
        Index(
            "uq_signal_review_cases_one_open",
            "signal_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_signal_review_cases_queue", "status", "opened_at", "id"),
    )

    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[ReviewReason] = mapped_column(
        vocabulary(ReviewReason, "review_reason_values"), nullable=False
    )
    status: Mapped[ReviewStatus] = mapped_column(
        vocabulary(ReviewStatus, "review_status_values"), nullable=False
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[ReviewResolution | None] = mapped_column(
        vocabulary(ReviewResolution, "review_resolution_values")
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(String(1000))
    selected_disease_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("diseases.id", ondelete="RESTRICT")
    )
    selected_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT")
    )


class SignalReviewCandidate(Base):
    __tablename__ = "signal_review_candidates"
    __table_args__ = (
        CheckConstraint("match_score >= 0 AND match_score <= 1", name="match_score_range"),
    )
    review_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("signal_review_cases.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), primary_key=True
    )
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
```

Also enforce resolution target compatibility with named check constraints from
the design; export both models from `models/__init__.py`.

- [ ] **Step 4: Run focused tests and confirm green**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/backend/src/episignal_backend/db/types.py packages/backend/src/episignal_backend/models packages/backend/tests/test_models.py packages/backend/tests/test_review_documents.py
git commit -m "feat(review): define review case model"
```

## Task 2: Add reversible schema expansion and conservative backfill

**Files:**

- Create: `database/migrations/versions/20260829_0010_manual_review_cases.py`
- Modify: `apps/api/tests/test_migrations.py`
- Create: `apps/api/integration_tests/test_manual_review_migration.py`
- Modify: `packages/backend/src/episignal_backend/schema_check.py`
- Modify: `packages/backend/tests/test_schema_check.py`

- [ ] **Step 1: Write failing migration source and round-trip tests**

Add tests proving revision order, table creation, the partial unique index,
`dismissed` in the processing-status constraint, ordered backfill predicates,
and guarded downgrade:

```python
def test_manual_review_migration_is_ordered_and_non_destructive() -> None:
    module = _load_revision("20260829_0010_manual_review_cases")
    source = _revision_source("20260829_0010_manual_review_cases")
    sql = render_offline("upgrade", "20260829_0010")
    assert module.down_revision == "20260828_0009"
    assert "create table signal_review_cases" in sql
    assert "create table signal_review_candidates" in sql
    assert "uq_signal_review_cases_one_open" in sql
    assert "dismissed" in sql
    assert "legacy_unclassified" in source
    assert "delete from signals" not in source.lower()
    assert "drop table signals" not in source.lower()


def test_manual_review_downgrade_refuses_to_erase_audit_history() -> None:
    source = _revision_source("20260829_0010_manual_review_cases")
    assert "Cannot downgrade manual review schema after review data exists" in source
```

The migration must render offline without executing its live verification
queries. Add `apps/api/integration_tests/test_manual_review_migration.py` for a
dedicated PostgreSQL database supplied only through
`EPISIGNAL_TEST_DATABASE_URL`. Its fixture must reject a URL equal to
`EPISIGNAL_DATABASE_URL`, upgrade an empty database to `0009`, insert exactly
five synthetic rows (quarantine, null text, rejected extraction, missing
disease, and legacy fallback), upgrade to `0010`, and assert one open case per
row plus unchanged title, raw text, hash, extraction, and processing status.

- [ ] **Step 2: Run migration tests and confirm red**

```powershell
uv run pytest apps/api/tests/test_migrations.py packages/backend/tests/test_schema_check.py -q
```

Expected: failure because revision `0010` and new contract values do not exist.

- [ ] **Step 3: Implement expand, backfill, verification, and guarded downgrade**

Use Alembic operations with bound parameters. The upgrade must finish with a
per-signal cardinality check equivalent to:

```sql
SELECT s.id
FROM signals AS s
LEFT JOIN signal_review_cases AS c
  ON c.signal_id = s.id AND c.status = 'open'
WHERE s.processing_status = 'needs_review'
GROUP BY s.id
HAVING count(c.id) <> 1;
```

Also reject any open case whose signal is not at `needs_review`. Raise
`RuntimeError` if either query returns a row. Backfill reason precedence must
match the spec and use `legacy_unclassified` whenever the database cannot prove
a more specific cause. Do not hard-code the observed total `37`.

Downgrade first runs:

```sql
SELECT
  (SELECT count(*) FROM signal_review_cases) AS review_cases,
  (SELECT count(*) FROM signals WHERE processing_status = 'dismissed') AS dismissed;
```

If either value is non-zero, raise the exact guarded-downgrade message. Otherwise drop candidate
rows, cases, indexes, and constraints, then contract processing status.

- [ ] **Step 4: Run focused migration and schema tests**

Run the Step 2 command. Expected: pass.

- [ ] **Step 5: Exercise the dedicated migration database**

```powershell
$env:EPISIGNAL_TEST_DATABASE_URL = '<operator-provided disposable PostgreSQL URL>'
uv run pytest apps/api/integration_tests/test_manual_review_migration.py -q
```

Expected: forward backfill, per-signal reconciliation, unused-schema downgrade,
re-upgrade, and guarded-downgrade cases pass. The fixture drops only its own
synthetic rows/schema during cleanup. Never substitute the live
`EPISIGNAL_DATABASE_URL` or run `corepack pnpm db:rollback` against live data.

- [ ] **Step 6: Commit**

```powershell
git add database/migrations/versions/20260829_0010_manual_review_cases.py apps/api/tests/test_migrations.py apps/api/integration_tests/test_manual_review_migration.py packages/backend/src/episignal_backend/schema_check.py packages/backend/tests/test_schema_check.py
git commit -m "feat(review): migrate durable review cases"
```

## Task 3: Define review commands, read models, and storage interface

**Files:**

- Create: `packages/backend/src/episignal_backend/review/__init__.py`
- Create: `packages/backend/src/episignal_backend/review/documents.py`
- Create: `packages/backend/src/episignal_backend/review/protocol.py`
- Create: `packages/backend/tests/test_review_documents.py`
- Create: `packages/backend/tests/test_review_protocol.py`

- [ ] **Step 1: Write failing contract tests**

Test frozen, extra-forbid commands and exact action compatibility:

```python
def test_dismiss_requires_a_note() -> None:
    with pytest.raises(ValidationError):
        DismissCommand(
            case_id=uuid4(), action="dismiss", reviewed_by="operator", note=" "
        )


def test_reason_action_matrix_is_closed() -> None:
    assert ALLOWED_RESOLUTIONS[ReviewReason.EVENT_MATCH_AMBIGUOUS] == frozenset({
        ReviewResolution.LINK_EVENT,
        ReviewResolution.CREATE_EVENT,
        ReviewResolution.DISMISS,
    })
```

Use a hand-written fake and a mypy assertion to prove it satisfies
`ReviewRepository`; include methods `lock_review_case`, `signal_for_review`,
`candidate_event_ids`, `set_disease`, `reset_retrieval`, `mark_classified`,
`mark_extracted`, `mark_dismissed`, `resolve_case`, `commit`, and `rollback`.

- [ ] **Step 2: Run tests and confirm red**

```powershell
uv run pytest packages/backend/tests/test_review_documents.py packages/backend/tests/test_review_protocol.py -q
```

Expected: missing package/types.

- [ ] **Step 3: Implement complete Pydantic types and protocol**

Use a real discriminated union so impossible target fields do not exist on the
wrong command type:

```python
class ReviewCommandBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: UUID
    reviewed_by: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("reviewed_by")
    @classmethod
    def reviewed_by_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reviewed_by must not be blank")
        return value

    @field_validator("note")
    @classmethod
    def note_is_not_blank_when_present(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("note must not be blank")
        return value


class RetryRetrievalCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.RETRY_RETRIEVAL]


class RetryExtractionCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.RETRY_EXTRACTION]


class AssignDiseaseCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.ASSIGN_DISEASE]
    disease_id: UUID


class RetryGeocodingCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.RETRY_GEOCODING]


class LinkEventCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.LINK_EVENT]
    event_id: UUID


class CreateEventCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.CREATE_EVENT]


class DismissCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.DISMISS]

    note: str = Field(min_length=1, max_length=1000)


ResolveReviewCommand = Annotated[
    RetryRetrievalCommand
    | RetryExtractionCommand
    | AssignDiseaseCommand
    | RetryGeocodingCommand
    | LinkEventCommand
    | CreateEventCommand
    | DismissCommand,
    Field(discriminator="action"),
]
```

Define frozen queue/read/result types for every field in the design. The
protocol must contain only operations used by
`resolve_review_case`; queue reads remain a separate session function.

- [ ] **Step 4: Run tests plus mypy**

```powershell
uv run pytest packages/backend/tests/test_review_documents.py packages/backend/tests/test_review_protocol.py -q
uv run mypy packages/backend/src/episignal_backend/review packages/backend/tests/test_review_protocol.py
```

Expected: both commands exit 0.

- [ ] **Step 5: Commit**

```powershell
git add packages/backend/src/episignal_backend/review packages/backend/tests/test_review_documents.py packages/backend/tests/test_review_protocol.py
git commit -m "feat(review): define resolution interface"
```

## Task 4: Persist typed case opening, queue reads, and automatic recovery

**Files:**

- Create: `packages/backend/src/episignal_backend/review/repository.py`
- Create: `packages/backend/tests/test_review_repository.py`

- [ ] **Step 1: Write failing repository tests**

Add five tests named
`test_open_review_reuses_the_existing_open_case`,
`test_ambiguous_review_snapshots_each_candidate_score`,
`test_automatic_recovery_closes_only_the_open_retrieval_case`,
`test_queue_orders_oldest_then_uuid_and_never_returns_raw_text`, and
`test_queue_skips_malformed_extraction_but_keeps_safe_signal_facts`. Each test
must assert hand-written case IDs, reasons, candidate scores, status changes,
and returned safe fields as applicable.

Use SQLAlchemy session mocks in the same style as
`packages/backend/tests/test_event_repository.py`. Expected queue values must
be hand-written literals, not recomputed with repository helpers.

- [ ] **Step 2: Run tests and confirm red**

```powershell
uv run pytest packages/backend/tests/test_review_repository.py -q
```

Expected: missing adapter/functions.

- [ ] **Step 3: Implement the SQLAlchemy adapter**

Expose `SqlAlchemyReviewRepository.open_review(signal_id, *, reason,
candidate_scores=None) -> UUID`,
`SqlAlchemyReviewRepository.recover_retrieval_automatically(signal_id) ->
None`, and `query_review_queue(session, *, limit=50, offset=0) ->
ReviewQueuePage` with those exact names and defaults.

Do not use a mutable mapping default in final code; use `None` and normalize to
an empty mapping. Insert/reuse behavior must tolerate the partial-unique race by
catching only the named unique violation, rolling back to a savepoint, and
reading the existing open case. Queue assembly joins `Signal`, `Source`,
`Disease`, locations, candidates, and events in bounded queries. Never select
`Signal.raw_text` or `AiRequest` payload fields for the response.

- [ ] **Step 4: Run focused tests**

Run the Step 2 command. Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/backend/src/episignal_backend/review/repository.py packages/backend/tests/test_review_repository.py
git commit -m "feat(review): store and query review cases"
```

## Task 5: Make every `needs_review` writer record a typed cause

**Files:**

- Modify: `packages/backend/src/episignal_backend/ai/protocol.py`
- Modify: `packages/backend/src/episignal_backend/ai/repository.py`
- Modify: `packages/backend/src/episignal_backend/ai/classify.py`
- Modify: `packages/backend/src/episignal_backend/ai/extract.py`
- Modify: `packages/backend/src/episignal_backend/ingestion/repository.py`
- Modify: `packages/backend/src/episignal_backend/ingestion/discovery.py`
- Modify: `packages/backend/src/episignal_backend/events/protocol.py`
- Modify: `packages/backend/src/episignal_backend/events/repository.py`
- Modify: `packages/backend/src/episignal_backend/events/assemble.py`
- Delete: `packages/backend/src/episignal_backend/ai/requeue.py`
- Modify: `packages/backend/tests/test_ai_classify.py`
- Modify: `packages/backend/tests/test_ai_extract.py`
- Modify: `packages/backend/tests/test_discovery_repository.py`
- Modify: `packages/backend/tests/test_discovery_retry.py`
- Modify: `packages/backend/tests/test_event_assemble.py`
- Modify: `packages/backend/tests/test_event_repository.py`
- Delete: `packages/backend/tests/test_ai_requeue.py`

- [ ] **Step 1: Convert the AI review writers test-first**

In `test_ai_classify.py` and `test_ai_extract.py`, replace fake review-ID sets
with captured calls:

```python
self.review_calls: list[tuple[UUID, ReviewReason, dict[UUID, float]]] = []

def open_review(
    self,
    signal_id: UUID,
    *,
    reason: ReviewReason,
    candidate_scores: Mapping[UUID, float] | None = None,
) -> None:
    self.review_calls.append((signal_id, reason, dict(candidate_scores or {})))
```

Assert both rejection/exhaustion paths call `open_review(...,
reason=EXTRACTION_REJECTED)`. Run:

```powershell
uv run pytest packages/backend/tests/test_ai_classify.py packages/backend/tests/test_ai_extract.py -q
```

Expected: fail on the old protocol. Change the AI protocol, repository, classify,
and extract writers so the signal status and typed case write share one
transaction. Run the command again. Expected: pass.

- [ ] **Step 2: Convert discovery failure, retry exhaustion, and recovery test-first**

In `test_discovery_repository.py` and `test_discovery_retry.py`, first assert:

- initial contentless discovery opens `RETRIEVAL_FAILED`;
- `record_failed_attempt(signal_id, max_attempts=max_attempts)` increments the
  attempt and opens a new `RETRIEVAL_FAILED` case exactly when the reset budget
  is exhausted;
- successful promotion closes only the open retrieval case as
  `RECOVERED_AUTOMATICALLY`;
- a non-retrieval case is never closed by promotion.

Run:

```powershell
uv run pytest packages/backend/tests/test_discovery_repository.py packages/backend/tests/test_discovery_retry.py packages/backend/tests/test_discovery_pipeline.py -q
```

Expected: fail on the old signatures. Update `ingestion/protocol.py`,
`ingestion/repository.py`, and `ingestion/discovery.py`; pass `max_attempts` from
`run_stub_retrieval`, and make the attempt increment plus case opening one
transaction. Run the command again. Expected: pass.

- [ ] **Step 3: Convert event refusal and unclusterable causes test-first**

In `test_event_assemble.py`, add separate cases for missing disease, missing or
unresolved representative location, and ambiguous match. Assert:

```python
assert repo.review_calls[missing_disease.signal_id].reason is ReviewReason.DISEASE_UNRESOLVED
assert repo.review_calls[missing_location.signal_id].reason is ReviewReason.LOCATION_UNRESOLVED
assert repo.review_calls[ambiguous.signal_id].candidate_scores == {
    qualifying_a: 0.81,
    qualifying_b: 0.74,
}
```

Include a `0.59` candidate below the configured `0.60` threshold and assert it
is absent. Run the two event suites and confirm red. Then branch unclusterable
signals explicitly by disease versus representative location and filter
`decision.candidate_scores` to `score >= match_threshold` before calling
`open_review`. The status and case write remain one repository transaction.
Run again and expect pass.

- [ ] **Step 4: Retire the superseded one-off requeue and scan all writers**

Delete `ai/requeue.py` and `test_ai_requeue.py`; repository search at planning
time found no production caller. Its historical execution remains documented in
the extraction-stall report. Remove or make private every public bare
`mark_needs_review` operation, then run:

```powershell
rg -n "mark_needs_review|processing_status\s*=\s*ProcessingStatus\.NEEDS_REVIEW|processing_status = 'needs_review'" packages/backend/src
```

Expected: only migration/backfill compatibility code or the typed review
adapter remains; inspect every match. Also run `rg -n "ai\.requeue|requeue_extraction_backlog" packages apps`
and expect no source/test caller.

- [ ] **Step 5: Run the complete affected set and mypy**

```powershell
uv run pytest packages/backend/tests/test_ai_classify.py packages/backend/tests/test_ai_extract.py packages/backend/tests/test_discovery_repository.py packages/backend/tests/test_discovery_retry.py packages/backend/tests/test_discovery_pipeline.py packages/backend/tests/test_event_assemble.py packages/backend/tests/test_event_repository.py -q
```

Then:

```powershell
uv run mypy packages/backend/src
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add packages/backend/src/episignal_backend/ai packages/backend/src/episignal_backend/ingestion packages/backend/src/episignal_backend/events packages/backend/tests
git commit -m "feat(review): record every review cause"
```

## Task 6: Extract one event-finalization implementation

**Files:**

- Create: `packages/backend/src/episignal_backend/events/finalize.py`
- Create: `packages/backend/tests/test_event_finalize.py`
- Modify: `packages/backend/src/episignal_backend/events/assemble.py`
- Modify: `packages/backend/tests/test_event_assemble.py`

- [ ] **Step 1: Add characterization tests for durable effects**

For both attach and create, assert the exact sequence-independent result:

```python
assert repo.matched_signal_ids == {signal.signal_id}
assert repo.recorded_observations == [(event_id, signal.signal_id)]
assert {row[0] for row in repo.added_locations} == {event_id}
assert event_id in repo.applied_scores
```

Add equivalent tests calling planned `attach_cluster` and `create_from_cluster`
directly. Expected values must not call score helpers.

- [ ] **Step 2: Run event tests and confirm new tests red**

```powershell
uv run pytest packages/backend/tests/test_event_finalize.py packages/backend/tests/test_event_assemble.py -q
```

Expected: missing finalization module.

- [ ] **Step 3: Move, do not duplicate, finalization behavior**

Create `attach_cluster(repo, cluster, *, event_id, match_score, now=None) ->
int` and `create_from_cluster(repo, cluster, *, now=None) -> tuple[UUID, int]`
with those exact names and defaults.

Move attachment, observation, location, matched-state, dual-score, and
verification-status writes from `run_event_assembly` into these functions.
Keep transaction ownership in caller/repository. `assemble.py` must delegate
and retain identical summary counts.

- [ ] **Step 4: Run event suite**

Run the Step 2 command. Expected: all pass with unchanged automated behavior.

- [ ] **Step 5: Commit**

```powershell
git add packages/backend/src/episignal_backend/events packages/backend/tests/test_event_finalize.py packages/backend/tests/test_event_assemble.py
git commit -m "refactor(events): share event finalization"
```

## Task 7: Resolve retry, disease, and dismissal cases transactionally

**Files:**

- Create: `packages/backend/src/episignal_backend/review/resolve.py`
- Modify: `packages/backend/src/episignal_backend/review/repository.py`
- Create: `packages/backend/tests/test_review_resolve.py`
- Modify: `packages/backend/tests/test_review_repository.py`

- [ ] **Step 1: Write one failing behavior test per command**

Cover `retry_retrieval`, `retry_extraction`, `assign_disease`, `dismiss`, wrong
reason/action, missing target, already-resolved case, and exception rollback:

```python
def test_assign_disease_returns_signal_to_geocoded() -> None:
    repo = FakeReviewRepository(reason=ReviewReason.DISEASE_UNRESOLVED)
    command = AssignDiseaseCommand(
        case_id=repo.case_id,
        action=ReviewResolution.ASSIGN_DISEASE,
        disease_id=DISEASE_ID,
        reviewed_by="shift operator",
    )
    result = resolve_review_case(repo, command)
    assert repo.disease_updates == [(repo.signal_id, DISEASE_ID)]
    assert result.processing_status is ProcessingStatus.GEOCODED
    assert repo.committed and not repo.rolled_back
```

- [ ] **Step 2: Run resolver tests and confirm red**

```powershell
uv run pytest packages/backend/tests/test_review_resolve.py packages/backend/tests/test_review_repository.py -q
```

Expected: missing resolver/adapter methods.

- [ ] **Step 3: Implement explicit resolution dispatch**

`resolve_review_case` must:

```python
case = repo.lock_review_case(command.case_id)
if case is None:
    raise ReviewCaseNotFound(command.case_id)
if case.status is ReviewStatus.RESOLVED:
    raise ReviewAlreadyResolved(command.case_id)
if command.action not in ALLOWED_RESOLUTIONS[case.reason]:
    raise ReviewActionNotAllowed(case.reason, command.action)
try:
    # exactly one explicit branch per allowed action
    repo.resolve_case(
        case_id=case.id,
        resolution=command.action,
        reviewed_by=command.reviewed_by,
        note=command.note,
        selected_disease_id=selected_disease_id,
        selected_event_id=selected_event_id,
        resolved_at=resolved_at,
    )
    repo.commit()
except Exception:
    repo.rollback()
    raise
```

Do not catch domain errors and turn them into success. `assign_disease` verifies
the canonical disease exists. `retry_retrieval` resets attempts to zero but
keeps `needs_review`; `retry_extraction` sets `classified`; dismissal sets
`dismissed`. `resolve_case` records identity, note, targets, and one shared UTC
timestamp.

- [ ] **Step 4: Run resolver/repository tests**

Run the Step 2 command. Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/backend/src/episignal_backend/review packages/backend/tests/test_review_resolve.py packages/backend/tests/test_review_repository.py
git commit -m "feat(review): resolve pipeline review cases"
```

## Task 8: Resolve ambiguous event cases through shared finalization

**Files:**

- Modify: `packages/backend/src/episignal_backend/review/protocol.py`
- Modify: `packages/backend/src/episignal_backend/review/resolve.py`
- Modify: `packages/backend/src/episignal_backend/review/repository.py`
- Modify: `packages/backend/tests/test_review_protocol.py`
- Modify: `packages/backend/tests/test_review_resolve.py`
- Modify: `packages/backend/tests/test_review_repository.py`

- [ ] **Step 1: Write failing link/create tests**

Prove link accepts only stored candidates, stale candidates fail without writes,
create returns the new event ID, both paths record observations/locations/scores,
and any finalization failure rolls back all work.

```python
def test_link_event_rejects_a_target_outside_the_snapshot() -> None:
    repo = FakeReviewRepository(
        reason=ReviewReason.EVENT_MATCH_AMBIGUOUS,
        candidate_event_ids={CANDIDATE_A, CANDIDATE_B},
    )
    with pytest.raises(ReviewTargetStale):
        resolve_review_case(repo, _link_command(event_id=OTHER_EVENT))
    assert repo.event_effects == []
    assert not repo.committed
```

- [ ] **Step 2: Run tests and confirm red**

Run:

```powershell
uv run pytest packages/backend/tests/test_review_resolve.py packages/backend/tests/test_review_repository.py packages/backend/tests/test_event_finalize.py -q
```

Expected: missing event-resolution methods.

- [ ] **Step 3: Add single-signal cluster loading and finalization**

The adapter loads `SignalForMatching` with the same mapping used by
`SqlAlchemyEventRepository`. Extract that mapping only if necessary to avoid
two implementations. Resolution builds one `StoryCluster`, then calls:

```python
attach_cluster(repo, cluster, event_id=command.event_id, match_score=snapshot_score)
# or
event_id, _ = create_from_cluster(repo, cluster)
```

The review repository may implement both protocols, or compose the existing
event repository over the same session. Do not create a second transaction.
Close the case only after finalization succeeds.

- [ ] **Step 4: Run focused tests and mypy**

Run the Step 2 command and:

```powershell
uv run mypy packages/backend/src/episignal_backend/review packages/backend/src/episignal_backend/events
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/backend/src/episignal_backend/review packages/backend/tests/test_review_protocol.py packages/backend/tests/test_review_resolve.py packages/backend/tests/test_review_repository.py
git commit -m "feat(review): resolve ambiguous event matches"
```

## Task 9: Add secret admin authentication and safe configuration

**Files:**

- Modify: `packages/backend/src/episignal_backend/config.py`
- Modify: `packages/backend/tests/test_config.py`
- Modify: `apps/api/src/episignal_api/dependencies.py`
- Modify: `apps/api/tests/test_api.py`
- Modify: `apps/api/.env.example`
- Modify: `.env.example`

- [ ] **Step 1: Write failing settings and auth dependency tests**

Test optional startup, unconfigured `503`, missing/wrong `401`, correct token,
constant-time comparison by monkeypatching `secrets.compare_digest`, and no
secret in error bodies or logs.

```python
def test_review_auth_accepts_the_configured_bearer_token() -> None:
    settings = Settings(
        database_url=DATABASE_URL,
        admin_token="operator-secret",
        _env_file=None,
    )
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials="operator-secret"
    )
    require_review_admin(credentials=credentials, settings=settings)
```

- [ ] **Step 2: Run focused tests and confirm red**

```powershell
uv run pytest packages/backend/tests/test_config.py apps/api/tests/test_api.py -q
```

Expected: missing setting/dependency.

- [ ] **Step 3: Implement optional secret and dependency**

Add:

```python
admin_token: SecretStr | None = Field(default=None, min_length=24)
```

Use `HTTPBearer(auto_error=False)`. If unconfigured, raise `503
ADMIN_REVIEW_DISABLED`; if missing, wrong scheme, or mismatch, raise one `401
ADMIN_AUTH_REQUIRED` response with `WWW-Authenticate: Bearer`. Compare encoded
secret strings with `secrets.compare_digest`. Never interpolate credentials.

Add `EPISIGNAL_ADMIN_TOKEN=` to both env examples. Keep all prior keys and
comments; no real values.

- [ ] **Step 4: Run tests and secret scan**

```powershell
uv run pytest packages/backend/tests/test_config.py apps/api/tests/test_api.py -q
git diff -- .env.example apps/api/.env.example
git grep -n -I -E 'EPISIGNAL_ADMIN_TOKEN=.+|Authorization: Bearer [A-Za-z0-9]+'
```

Expected: tests pass; diff contains empty/example values only; secret scan finds
no credential.

- [ ] **Step 5: Commit**

```powershell
git add packages/backend/src/episignal_backend/config.py packages/backend/tests/test_config.py apps/api/src/episignal_api/dependencies.py apps/api/tests/test_api.py .env.example apps/api/.env.example
git commit -m "feat(review): protect admin review access"
```

## Task 10: Expose authenticated queue reads

**Files:**

- Create: `apps/api/src/episignal_api/routes/reviews.py`
- Modify: `apps/api/src/episignal_api/dependencies.py`
- Modify: `apps/api/src/episignal_api/factory.py`
- Create: `apps/api/tests/test_reviews.py`

- [ ] **Step 1: Write failing endpoint tests**

Build a literal `ReviewQueuePage` fixture and assert exact JSON for title/source,
disease, locations, candidates, allowed actions, disease options, limit, and
offset. Add query bounds, auth, empty queue, malformed extraction tolerance, and
forbidden-key scans:

```python
for forbidden in ["raw_text", "source_span", "prompt", "api_key", "exception"]:
    assert f'"{forbidden}"' not in response.text
```

- [ ] **Step 2: Run API tests and confirm red**

```powershell
uv run pytest apps/api/tests/test_reviews.py -q
```

Expected: route not found.

- [ ] **Step 3: Implement dependency and response models**

Wire:

```python
router = APIRouter(
    prefix="/api/v1/admin/reviews",
    tags=["admin"],
    dependencies=[Depends(require_review_admin)],
)

@router.get("", response_model=ReviewQueueResponse)
def list_reviews(
    page: Annotated[ReviewQueuePage, Depends(get_review_queue_page)],
) -> ReviewQueueResponse:
    return ReviewQueueResponse.model_validate(page)
```

All response models use `ConfigDict(from_attributes=True, extra="forbid")`.
Bound `limit` to `1..50`, `offset >= 0`. Include the router in `create_app`.

- [ ] **Step 4: Run API tests**

Run the Step 2 command. Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/episignal_api/routes/reviews.py apps/api/src/episignal_api/dependencies.py apps/api/src/episignal_api/factory.py apps/api/tests/test_reviews.py
git commit -m "feat(review): expose authenticated review queue"
```

## Task 11: Expose transactional resolution and regenerate contracts

**Files:**

- Modify: `apps/api/src/episignal_api/routes/reviews.py`
- Modify: `apps/api/src/episignal_api/dependencies.py`
- Modify: `apps/api/src/episignal_api/factory.py`
- Modify: `apps/api/tests/test_reviews.py`
- Modify generated: `packages/contracts/openapi.json`
- Modify generated: `packages/contracts/src/index.d.ts`

- [ ] **Step 1: Write failing POST and error-mapping tests**

Test all action JSON shapes, exact success response, `401`, `404`, each `409`,
`422`, `503`, rollback behavior through dependency fake, and rejected extra
fields. Assert CORS permits `GET` and `POST` but no wider methods.

- [ ] **Step 2: Run endpoint tests and confirm red**

Run:

```powershell
uv run pytest apps/api/tests/test_reviews.py apps/api/tests/test_api.py -q
```

Expected: POST route absent.

- [ ] **Step 3: Implement POST and stable exception mapping**

Add:

```python
@router.post("/{case_id}/resolve", response_model=ReviewResolutionResponse)
def resolve_review(
    case_id: UUID,
    body: ReviewResolutionRequest,
    resolver: Annotated[ReviewResolver, Depends(get_review_resolver)],
) -> ReviewResolutionResponse:
    command = body.to_command(case_id)
    return ReviewResolutionResponse.model_validate(resolver(command))
```

Map domain exceptions to exact codes from the design. Do not return exception
text. Update CORS `allow_methods` to `['GET', 'POST']` only.

- [ ] **Step 4: Regenerate and prove contract parity**

```powershell
corepack pnpm contracts:generate
corepack pnpm contracts:check
uv run pytest apps/api/tests/test_reviews.py apps/api/tests/test_openapi.py -q
```

Expected: generated files change once; parity and tests pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/api/src/episignal_api packages/contracts apps/api/tests/test_reviews.py apps/api/tests/test_openapi.py
git commit -m "feat(review): resolve reviews through admin API"
```

## Task 12: Strictly validate the review API in the web client

**Files:**

- Create: `apps/web/src/lib/api-reviews.ts`
- Create: `apps/web/src/lib/api-reviews.test.ts`

- [ ] **Step 1: Read current installed Next.js data-fetching guidance**

```powershell
rg -n "client component|fetch|environment variable" apps/web/node_modules/next/dist/docs -g "*.md"
```

Read the matching App Router guides before editing. Record no copied docs in the
commit.

- [ ] **Step 2: Write failing independent validator tests**

Cover valid open queue, every invalid enum, extra/missing keys, malformed UUID
and datetime, score outside `0..1`, wrong candidate/disease shapes, item count
above limit, non-HTTP source URL, `401`, `503`, invalid JSON, timeout, and each
resolution response.

```typescript
expect(isReviewQueuePage(validFixture)).toBe(true);
expect(
  isReviewQueuePage(Object.assign({}, validFixture, { raw_text: "leak" })),
).toBe(false);
expect(isReviewQueuePage(withCandidateScore(1.01))).toBe(false);
```

- [ ] **Step 3: Run the focused test and confirm red**

```powershell
corepack pnpm --filter @episignal/web test -- src/lib/api-reviews.test.ts
```

Expected: module missing.

- [ ] **Step 4: Implement strict validators and fetch functions**

Derive static types from generated contracts but validate runtime data
independently. Export:

```typescript
export async function getReviewQueue(
  token: string,
  limit = 50,
  offset = 0,
): Promise<ReviewQueueState>;

export async function resolveReview(
  token: string,
  caseId: string,
  command: ReviewResolutionCommand,
): Promise<ReviewResolutionState>;
```

Send `Authorization` only as a header. Use `cache: "no-store"` and
`AbortSignal.timeout(5000)`. Return distinct `unauthorized`, `disabled`,
`conflict`, and `unavailable` states. Do not log the token or response body.

- [ ] **Step 5: Run focused tests**

Run the Step 3 command. Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add apps/web/src/lib/api-reviews.ts apps/web/src/lib/api-reviews.test.ts
git commit -m "feat(web): validate admin review contracts"
```

## Task 13: Build the accessible cause-specific review queue

**Files:**

- Create: `apps/web/src/components/admin-review-queue.tsx`
- Create: `apps/web/src/components/admin-review-queue.test.tsx`

- [ ] **Step 1: Write failing behavior and layout tests**

Use Testing Library and `userEvent` to prove:

- locked state asks for token and operator name;
- the token input has `type="password"` and no persistence call occurs;
- successful unlock renders an oldest-first case rail and selected-case
  decision workspace;
- each reason renders only allowed controls;
- missing disease uses canonical disease options;
- ambiguous candidates show public ID, title, verification status, and score;
- dismissal requires note plus confirmation;
- success removes the case and announces through `aria-live`;
- conflict/unavailable preserves the case and entered values;
- token never appears in rendered text or hrefs;
- icon-only buttons have accessible names and rendered text contains none of
  the emoji glyphs `📍`, `✕`, `⚠`, or `✓`.

- [ ] **Step 2: Run component test and confirm red**

```powershell
corepack pnpm --filter @episignal/web test -- src/components/admin-review-queue.test.tsx
```

Expected: component missing.

- [ ] **Step 3: Implement one isolated client component**

Credential and selection state stays local:

```tsx
"use client";

export function AdminReviewQueue() {
  const [token, setToken] = useState("");
  const [reviewedBy, setReviewedBy] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const [queue, setQueue] = useState<ReviewQueueState>({ status: "locked" });
  const [pendingCaseId, setPendingCaseId] = useState<string | null>(null);
}
```

Implement complete locked, loading, ready, empty, unauthorized, disabled,
conflict, and unavailable branches. Use a
desktop `case-rail` plus `decision-workspace`; DOM order remains rail then
workspace and CSS collapses it to one column below `768px`. Use semantic
headings, `<form>`, `<fieldset>`, `<legend>`, `<label>`, native `<select>`, and
buttons. Reuse existing text controls and CSS status marks; add no UI or icon
package. Decorative marks are `aria-hidden`, and icon-only controls have labels.
Keep one pending action per case. Require explicit confirmation for dismissal.
Render safe facts only. No token persistence, animation library, or generic form
system.

- [ ] **Step 4: Run component and client tests**

```powershell
corepack pnpm --filter @episignal/web test -- src/components/admin-review-queue.test.tsx src/lib/api-reviews.test.ts
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add apps/web/src/components/admin-review-queue.tsx apps/web/src/components/admin-review-queue.test.tsx
git commit -m "feat(web): add manual review queue"
```

## Task 14: Mount the inspired review workspace in the existing web shell

**Files:**

- Create: `apps/web/src/app/admin/reviews/page.tsx`
- Modify: `apps/web/src/app/globals.css`
- Modify: `apps/web/src/components/home-shell.tsx`
- Modify: `apps/web/src/components/home-shell.test.tsx`

- [ ] **Step 1: Add the failing navigation and route test**

In `home-shell.test.tsx`, assert the current masthead gains a `Review Queue`
link to `/admin/reviews` while its Map, Signals, Pipeline Monitor, and About
links remain. In `admin-review-queue.test.tsx`, import the route and assert it
renders `AdminReviewQueue`.

- [ ] **Step 2: Run the route seam and confirm red**

```powershell
corepack pnpm --filter @episignal/web test -- src/components/home-shell.test.tsx src/components/admin-review-queue.test.tsx
```

Expected: the missing link and route fail.

- [ ] **Step 3: Mount the page and navigation, then make the seam green**

Create the route exactly:

```tsx
import { AdminReviewQueue } from "@/components/admin-review-queue";

export default function AdminReviewsPage() {
  return <AdminReviewQueue />;
}
```

Add `<Link href="/admin/reviews">Review Queue</Link>` beside Pipeline Monitor
in the existing masthead. Run the Step 2 command. Expected: pass.

- [ ] **Step 4: Add one failing scoped visual-adaptation test**

In `admin-review-queue.test.tsx`, assert the ready state has `case-rail` then
`decision-workspace`, all actions retain accessible names, rendered text has no
decorative emoji, and no screenshot-derived severity, publisher, location, or
summary fixture is introduced. Read `apps/web/package.json` in the test and
assert its dependency keys are unchanged from the planning baseline:
`@episignal/contracts`, `maplibre-gl`, `next`, `react`, and `react-dom`.

- [ ] **Step 5: Adapt only the review workspace and make the test green**

Keep the current Fraunces/Inter loading, masthead markup, semantic CSS, Tailwind,
and MapLibre code unchanged. Add scoped `.review-console` descendants in
`globals.css`; do not replace `:root` values. Use these local values as the
reference adaptation:

```css
.review-console {
  --review-canvas: #061321;
  --review-panel: #0b1d2d;
  --review-line: #20384a;
  --review-ink: #f3f7fb;
  --review-muted: #9eb0c2;
  --review-accent: #37d6df;
}
```

Use Inter for operational content and existing `font-mono` utilities for IDs,
scores, and timestamps. Desktop is case rail plus decision workspace; below
`768px`, keep DOM order and collapse to one column. Use 1 px dividers, no blur
or glow, 44 px targets, and only short transform/opacity transitions that stop
under `prefers-reduced-motion`. Do not edit the radar, map, pipeline monitor,
global font loading, or global tokens. Run the Step 2 command. Expected: pass.

- [ ] **Step 6: Run web tests, typecheck, and production build**

```powershell
corepack pnpm --filter @episignal/web test
corepack pnpm --filter @episignal/web typecheck
corepack pnpm --filter @episignal/web build
```

Expected: all web tests pass and build lists `/`, `/admin/pipeline`, and
`/admin/reviews`.

- [ ] **Step 7: Inspect the review page at two viewports**

Run the app against a non-production API fixture. Open `/admin/reviews` at
`390x844` and `1440x900` in the in-app browser. At each size, inspect the locked,
ready, empty, and unavailable frames; confirm no horizontal page overflow,
clipped action, unreadable focus state, or sub-44 px interactive target. Record
the viewport results in the Task 15 report. A unit test or build does not replace
this browser proof.

- [ ] **Step 8: Commit**

```powershell
git add apps/web/src/app/admin/reviews/page.tsx apps/web/src/app/globals.css apps/web/src/components/home-shell.tsx apps/web/src/components/home-shell.test.tsx apps/web/src/components/admin-review-queue.test.tsx
git commit -m "feat(web): mount the inspired review workspace"
```

## Task 15: Review, verify, capture safe live proof, and report

**Files:**

- Modify: code/tests from earlier tasks only when review finds a concrete defect
- Modify: `STATUS.md` task ledger and verified baseline
- Create: `docs/reports/2026-08-29-subproject-m-report.md`

- [ ] **Step 1: Run the two-axis code review**

Load `.agents/skills/code-review/SKILL.md`. Fixed point is the commit immediately
before Task 1. Standards sources are `AGENTS.md`, `CONTEXT.md`,
`docs/agents/workflow.md`, `apps/web/AGENTS.md`, and applicable installed Next
docs. Spec source is
`docs/superpowers/specs/2026-08-29-manual-review-queue-design.md`.

Review standards and spec separately. Fix only concrete findings, add focused
regression tests first for behavior defects, and commit each correction.

- [ ] **Step 2: Run focused security and provenance scans**

```powershell
rg -n "mark_needs_review|processing_status = 'needs_review'" packages/backend/src
git grep -n -I -E 'EPISIGNAL_(ADMIN_TOKEN|OPENROUTER_API_KEY)=.+|Authorization: Bearer [A-Za-z0-9]+'
rg -n 'raw_text|source_span|prompt|api_key|exception' apps/api/src/episignal_api/routes/reviews.py apps/web/src/lib/api-reviews.ts apps/web/src/components/admin-review-queue.tsx
```

Expected: each review transition is typed; no real secret; forbidden fields do
not enter response construction or rendered queue data. Inspect legitimate
validation/test matches rather than accepting raw zero counts blindly.

- [ ] **Step 3: Run schema and database checks**

```powershell
corepack pnpm db:migrate
corepack pnpm db:check
uv run --package episignal-backend python -m episignal_backend.schema_check
```

Expected: migration head `20260829_0010`, `database=up`, `postgis=up`, and schema
contract clean.

- [ ] **Step 4: Capture non-destructive live queue proof**

With `EPISIGNAL_ADMIN_TOKEN` set locally, call the authenticated list endpoint
and record only:

- total signals at `needs_review` before migration;
- total open review cases after migration;
- counts by typed reason;
- one redacted representative response per reason;
- confirmation that raw text, prompts, credentials, exception messages, and
  patient-level data are absent.

Exercise one safe resolution only if a clearly synthetic disposable fixture
signal already exists, and record its ID and cleanup. Do not dismiss, reassign,
relink, or create an event from live reporting solely for proof. If no such
fixture exists, do not substitute automated tests for this live acceptance
condition: record the blocker, leave `M` at `building`, and hand back to the
planner without claiming completion.

- [ ] **Step 5: Run the full completion gate**

Load `.agents/skills/verify-and-stop/SKILL.md`, then run:

```powershell
corepack pnpm verify
```

Expected: exit code 0. Record exact Python count, warning count, web test count
and file count, formatted-file count, mypy source-file count, contract result,
and production routes. If web workers fail before executing tests with `Test
Files no tests`, rerun `corepack pnpm --filter @episignal/web test` alone before
classifying it; otherwise treat every failure as real.

- [ ] **Step 6: Write the completion report and update worker-owned tracking**

Create `docs/reports/2026-08-29-subproject-m-report.md` with:

- task/commit ledger;
- schema forward and guarded rollback evidence;
- live pre/post case reconciliation;
- authentication and forbidden-field proof;
- event-finalization parity proof;
- exact focused and full-gate outputs;
- limitations and deliberately omitted live mutations.

Tick each `STATUS.md` task only in the commit that completes it. In this final
commit, update the **Verified baseline** to the exact commit/state where the full
gate ran. Do not mark `M` verified in `ROADMAP.md`; planner owns that transition.

- [ ] **Step 7: Commit report and hand back**

```powershell
git add STATUS.md docs/reports/2026-08-29-subproject-m-report.md
git commit -m "docs: report manual review queue completion"
git status --short --branch
```

Expected: clean tree. Hand back fixed-point commit, final commit, review
findings/corrections, exact verification output, live proof, and report path.
Stop. Do not start `G`, `D2b`, `F`, or any hygiene deletion.
