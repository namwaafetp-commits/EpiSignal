# Stage 0 Deduplication and Rule Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject obviously irrelevant articles before any page fetch, and resolve syndicated copies to one primary signal per story, so that no AI call in sub-project C is ever spent on junk or on a republished duplicate.

**Architecture:** Two gates either side of the existing page fetch. Gate one is a negative-only relevance filter that runs inside `run_discovery` on GDELT metadata and writes rejections to their own table. Gate two is a new `run_dedupe` pass over stored signals that marks each one `normalized` or `duplicate`, a duplicate carrying a self-referencing pointer to its primary. Both gates are pure decision modules depending only on Protocols, matching how `discovery.py` is already built.

**Tech Stack:** Python 3.12, SQLAlchemy 2 ORM, Alembic, Pydantic v2, pytest, PostgreSQL. `uv` runs everything; `pnpm` fronts the commands.

**Spec:** `docs/superpowers/specs/2026-08-27-gdelt-stage0-filtering-design.md`

---

## Before you start

Read the spec. Then read these three files, which this plan extends rather than replaces:

- `packages/backend/src/episignal_backend/ingestion/discovery.py` — the pipeline gate one joins.
- `packages/backend/src/episignal_backend/ingestion/repository.py` — the storage boundary.
- `packages/backend/tests/test_discovery_pipeline.py` — the fake-repository test style every pure-module test here follows.

Three house rules that are not obvious from the code:

1. **Decision modules never import SQLAlchemy or httpx.** `filtering.py`, `similarity.py`, and `dedupe.py` depend only on `documents.py` and `protocol.py`. This is what lets every decision be tested with in-memory fakes.
2. **Timestamps are never substituted for one another.** `published_at`, `first_seen_at`, `retrieved_at`, and `gdelt_seen_at` mean four different things. Never fill one from another.
3. **A rejection must always name its rule.** An unattributed rejection cannot be reviewed, and a wrongly rejected article is a missed outbreak.

Run the full gate after every task:

```bash
uv run pytest
```

---

## File structure

**Create:**

| Path | Responsibility |
| --- | --- |
| `packages/backend/src/episignal_backend/ingestion/filtering.py` | Pure. Compile filter rules, decide whether one article is rejected. |
| `packages/backend/src/episignal_backend/ingestion/similarity.py` | Pure. Title and body normalization, Jaccard similarity. |
| `packages/backend/src/episignal_backend/ingestion/dedupe.py` | Pure. `run_dedupe` over a `DedupeRepository`. |
| `packages/backend/src/episignal_backend/dedupe_runner.py` | CLI entry point for `pnpm dedupe:signals`. |
| `database/migrations/versions/20260827_0004_stage0_filtering.py` | Schema change. |
| `database/seeds/filter_rules.json` | The seeded rule library. |
| `packages/backend/tests/test_stage0_documents.py` | DTO validation tests. |
| `packages/backend/tests/test_filtering.py` | Gate one decision tests. |
| `packages/backend/tests/test_similarity.py` | Normalization and similarity tests. |
| `packages/backend/tests/test_dedupe.py` | `run_dedupe` tests against a fake repository. |
| `packages/backend/tests/test_dedupe_repository.py` | `SqlAlchemyDedupeRepository` tests. |
| `packages/backend/tests/test_dedupe_runner.py` | CLI tests. |
| `packages/backend/tests/fixtures/syndicated_body_a.txt` | Body of the primary copy. |
| `packages/backend/tests/fixtures/syndicated_body_b.txt` | Body of the syndicated copy, differing only in affiliate boilerplate. |
| `packages/backend/tests/fixtures/independent_body.txt` | Independent report on the same outbreak, same headline, different prose. |

**Modify:**

| Path | Change |
| --- | --- |
| `packages/backend/src/episignal_backend/db/types.py` | `+ FilterRuleGroup`, `+ ProcessingStatus.DUPLICATE` |
| `packages/backend/src/episignal_backend/ingestion/documents.py` | `+ FilterRule`, `+ Rejection`, `+ ComparableSignal` |
| `packages/backend/src/episignal_backend/ingestion/protocol.py` | `+ DiscoveryRepository.filter_rules/record_rejection`, `+ DedupeRepository` |
| `packages/backend/src/episignal_backend/models/discovery.py` | `+ SignalFilterRule`, `+ RejectedSighting` |
| `packages/backend/src/episignal_backend/models/signal.py` | `+ duplicate_of_signal_id` and its index |
| `packages/backend/src/episignal_backend/models/__init__.py` | Export the two new models |
| `packages/backend/src/episignal_backend/ingestion/repository.py` | `+ filter_rules`, `+ record_rejection`, `+ SqlAlchemyDedupeRepository` |
| `packages/backend/src/episignal_backend/ingestion/discovery.py` | Gate one, `DiscoveryResult.rejected`, `DiscoveryResult.rules_invalid` |
| `packages/backend/src/episignal_backend/seeds.py` | `+ FilterRuleSeed`, `+ load_filter_rules`, seed them |
| `packages/backend/src/episignal_backend/config.py` | Five `stage0_*` settings |
| `packages/backend/src/episignal_backend/discover_runner.py` | Print the two new counters |
| `package.json` | `+ dedupe:signals` |
| `packages/backend/tests/test_discovery_pipeline.py` | Fake repository gains the two new methods; gate one tests |
| `packages/backend/tests/test_seeds.py` | Filter rule seeding |
| `packages/backend/tests/test_models.py` | The two new models |

---

## Task 1: Vocabulary for filter groups and the duplicate status

**Files:**
- Modify: `packages/backend/src/episignal_backend/db/types.py`
- Test: `packages/backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_models.py`:

```python
def test_filter_rule_groups_are_stored_as_their_values() -> None:
    from episignal_backend.db.types import FilterRuleGroup

    assert FilterRuleGroup.TITLE_EXCLUSION.value == "title_exclusion"
    assert FilterRuleGroup.DOMAIN_BLOCKLIST.value == "domain_blocklist"


def test_duplicate_is_a_processing_status() -> None:
    from episignal_backend.db.types import ProcessingStatus

    assert ProcessingStatus.DUPLICATE.value == "duplicate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_models.py -k "filter_rule_groups or duplicate_is_a" -v`
Expected: FAIL with `ImportError: cannot import name 'FilterRuleGroup'`

- [ ] **Step 3: Write minimal implementation**

In `packages/backend/src/episignal_backend/db/types.py`, add the new enum after `DiscoveryMethod`:

```python
class FilterRuleGroup(StrEnum):
    TITLE_EXCLUSION = "title_exclusion"
    DOMAIN_BLOCKLIST = "domain_blocklist"
```

In the same file, add one member to `ProcessingStatus`, immediately before `FAILED`:

```python
class ProcessingStatus(StrEnum):
    FETCHED = "fetched"
    NORMALIZED = "normalized"
    CLASSIFIED = "classified"
    EXTRACTED = "extracted"
    GEOCODED = "geocoded"
    MATCHED = "matched"
    PUBLISHED = "published"
    # Terminal, like FAILED: a duplicate is not processed further, but unlike
    # FAILED it is a correct outcome rather than an error.
    DUPLICATE = "duplicate"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_models.py -k "filter_rule_groups or duplicate_is_a" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/db/types.py packages/backend/tests/test_models.py
git commit -m "feat: add the Stage 0 filter vocabulary and duplicate status"
```

---

## Task 2: Contracts for rules, rejections, and comparable signals

**Files:**
- Modify: `packages/backend/src/episignal_backend/ingestion/documents.py`
- Test: `packages/backend/tests/test_stage0_documents.py`

Naming note: these DTOs are deliberately named apart from the tables they load from, exactly as `QueryRule` is named apart from `GdeltQueryRule`. `FilterRule` loads from `SignalFilterRule`, `Rejection` is written to `RejectedSighting`.

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_stage0_documents.py`:

```python
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from episignal_backend.db.types import FilterRuleGroup
from episignal_backend.ingestion.documents import ComparableSignal, FilterRule, Rejection

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


def test_filter_rule_carries_its_group_and_pattern() -> None:
    rule = FilterRule(
        id=uuid4(),
        rule_group=FilterRuleGroup.TITLE_EXCLUSION,
        pattern=r"\bviral video\b",
        label="Viral content",
    )

    assert rule.rule_group is FilterRuleGroup.TITLE_EXCLUSION
    assert rule.pattern == r"\bviral video\b"


def test_filter_rule_rejects_a_blank_pattern() -> None:
    with pytest.raises(ValidationError):
        FilterRule(rule_group=FilterRuleGroup.DOMAIN_BLOCKLIST, pattern="", label="Empty")


def test_rejection_requires_an_aware_rejected_at() -> None:
    with pytest.raises(ValidationError):
        Rejection(
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            title="Outbreak of violence in the capital",
            domain="example.com",
            rejected_at=datetime(2026, 8, 27, 9, 0),
        )


def test_rejection_allows_a_missing_sighting_time() -> None:
    rejection = Rejection(
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        title="Outbreak of violence in the capital",
        domain="example.com",
        rejected_at=NOW,
    )

    assert rejection.gdelt_seen_at is None
    assert rejection.filter_rule_id is None


def test_comparable_signal_requires_body_text() -> None:
    with pytest.raises(ValidationError):
        ComparableSignal(
            id=uuid4(),
            canonical_url="https://example.com/a",
            title="Measles cases rise",
            raw_text="   ",
            content_hash="a" * 64,
            first_seen_at=NOW,
        )


def test_comparable_signal_defaults_to_no_primary() -> None:
    signal = ComparableSignal(
        id=uuid4(),
        canonical_url="https://example.com/a",
        title="Measles cases rise",
        raw_text="Eighteen cases were confirmed.",
        content_hash="a" * 64,
        first_seen_at=NOW,
    )

    assert signal.published_at is None
    assert signal.duplicate_of_signal_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_stage0_documents.py -v`
Expected: FAIL with `ImportError: cannot import name 'ComparableSignal'`

- [ ] **Step 3: Write minimal implementation**

In `packages/backend/src/episignal_backend/ingestion/documents.py`, add `FilterRuleGroup` to the existing `db.types` import:

```python
from episignal_backend.db.types import FilterRuleGroup, ProcessingStatus, SignalType
```

Then append these three classes to the end of the file:

```python
class FilterRule(BaseModel):
    """One stored Stage 0 rule.

    A `title_exclusion` pattern is a regular expression matched against the
    article title. A `domain_blocklist` pattern is a host, matched exactly or as
    a dotted suffix, never as a regular expression.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID | None = None
    rule_group: FilterRuleGroup
    pattern: str = Field(min_length=1)
    label: str = Field(min_length=1)


class Rejection(BaseModel):
    """A GDELT sighting dropped before its page was fetched.

    It is not a signal: no page was retrieved, so there is no `retrieved_at` and
    no body to hash. It is kept so that a wrongly rejected article stays
    findable, which is the only defence against a filter rule that is too broad.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    gdelt_seen_at: datetime | None = None
    rejected_at: datetime
    filter_rule_id: UUID | None = None

    @field_validator("rejected_at")
    @classmethod
    def rejected_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @field_validator("gdelt_seen_at")
    @classmethod
    def gdelt_seen_at_is_aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_aware(value)


class ComparableSignal(BaseModel):
    """A stored signal with enough of itself to be compared to another.

    Used both for the queue awaiting a decision and for the candidates it is
    compared against: the two carry the same fields and differ only in the query
    that produced them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    canonical_url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    first_seen_at: datetime
    published_at: datetime | None = None
    duplicate_of_signal_id: UUID | None = None

    @field_validator("raw_text")
    @classmethod
    def raw_text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("raw_text must not be blank")
        return value

    @field_validator("first_seen_at")
    @classmethod
    def first_seen_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @field_validator("published_at")
    @classmethod
    def published_at_is_aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_aware(value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_stage0_documents.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/documents.py packages/backend/tests/test_stage0_documents.py
git commit -m "feat: add the Stage 0 filtering and comparison contracts"
```

---

## Task 3: Models for filter rules and rejected sightings

**Files:**
- Modify: `packages/backend/src/episignal_backend/models/discovery.py`
- Modify: `packages/backend/src/episignal_backend/models/signal.py`
- Modify: `packages/backend/src/episignal_backend/models/__init__.py`
- Test: `packages/backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_models.py`:

```python
def test_filter_rules_are_unique_per_group_and_pattern() -> None:
    from episignal_backend.models import SignalFilterRule

    constraints = {
        constraint.name for constraint in SignalFilterRule.__table__.constraints
    }
    assert "uq_filter_rules_rule_group" in constraints
    assert SignalFilterRule.__tablename__ == "filter_rules"


def test_rejected_sighting_is_unique_per_canonical_url() -> None:
    from episignal_backend.models import RejectedSighting

    constraints = {
        constraint.name for constraint in RejectedSighting.__table__.constraints
    }
    assert "uq_rejected_sightings_canonical_url" in constraints


def test_rejected_sighting_keeps_its_rule_when_the_rule_is_deleted() -> None:
    from episignal_backend.models import RejectedSighting

    foreign_key = next(iter(RejectedSighting.__table__.c.filter_rule_id.foreign_keys))
    assert foreign_key.ondelete == "SET NULL"


def test_signal_points_at_its_primary_when_duplicate() -> None:
    from episignal_backend.models import Signal

    column = Signal.__table__.c.duplicate_of_signal_id
    assert column.nullable is True
    foreign_key = next(iter(column.foreign_keys))
    assert foreign_key.column.table.name == "signals"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_models.py -k "filter_rules_are_unique or rejected_sighting or points_at_its_primary" -v`
Expected: FAIL with `ImportError: cannot import name 'SignalFilterRule'`

- [ ] **Step 3: Write minimal implementation**

Replace the imports at the top of `packages/backend/src/episignal_backend/models/discovery.py` with:

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin, TimestampMixin
from episignal_backend.db.types import FilterRuleGroup, vocabulary
```

Then append to the same file:

```python
class SignalFilterRule(IdentityMixin, TimestampMixin, Base):
    """A Stage 0 rule, editable in the database without a deployment.

    Named apart from the `FilterRule` contract for the same reason
    `GdeltQueryRule` is named apart from `QueryRule`: one is a row, the other is
    what the pipeline is handed.
    """

    __tablename__ = "filter_rules"
    __table_args__ = (
        UniqueConstraint("rule_group", "pattern", name="uq_filter_rules_rule_group"),
    )

    rule_group: Mapped[FilterRuleGroup] = mapped_column(
        vocabulary(FilterRuleGroup, "filter_rule_group_values"), nullable=False
    )
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class RejectedSighting(IdentityMixin, TimestampMixin, Base):
    """An article dropped before its page was fetched.

    Deliberately not a `signals` row: `signals.retrieved_at` and
    `signals.content_hash` are both NOT NULL, and this article was never
    retrieved and has no body, so storing it there would mean inventing a
    retrieval time.
    """

    __tablename__ = "rejected_sightings"
    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_rejected_sightings_canonical_url"),
        Index("ix_rejected_sightings_filter_rule_id", "filter_rule_id"),
        Index("ix_rejected_sightings_rejected_at", "rejected_at"),
    )

    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    gdelt_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # SET NULL, matching signals.query_rule_id: retiring a rule must not delete
    # the record of what it rejected.
    filter_rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("filter_rules.id", ondelete="SET NULL")
    )
```

In `packages/backend/src/episignal_backend/models/signal.py`, add one index to `__table_args__`, immediately after `Index("ix_signals_first_seen_at", "first_seen_at")`:

```python
        Index("ix_signals_duplicate_of_signal_id", "duplicate_of_signal_id"),
```

and add the column at the end of the class, after `query_rule_id`:

```python
    # Self-referencing: a syndicated copy keeps its own row and its own
    # publisher, and points at the copy that was seen first. Flattened on
    # assignment, so this never leads to another duplicate.
    duplicate_of_signal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL")
    )
```

In `packages/backend/src/episignal_backend/models/__init__.py`, extend the discovery import and `__all__`:

```python
from episignal_backend.models.discovery import (
    GdeltQueryRule,
    RejectedSighting,
    SignalFilterRule,
)
```

```python
__all__ = [
    "Disease",
    "Event",
    "EventLocation",
    "EventObservation",
    "EventSignal",
    "GdeltQueryRule",
    "Pathogen",
    "RejectedSighting",
    "Signal",
    "SignalFilterRule",
    "Source",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_models.py -v`
Expected: PASS, no regressions in the existing model tests

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/models packages/backend/tests/test_models.py
git commit -m "feat: model filter rules, rejected sightings, and the duplicate pointer"
```

---

## Task 4: Migration 20260827_0004

**Files:**
- Create: `database/migrations/versions/20260827_0004_stage0_filtering.py`

There is no unit test for a migration in this repository; it is verified by applying it. The `processing_status` check constraint must be dropped and recreated because the vocabulary is stored as a check constraint over values, not as a native PostgreSQL enum.

- [ ] **Step 1: Write the migration**

Create `database/migrations/versions/20260827_0004_stage0_filtering.py`:

```python
"""add Stage 0 filtering and deduplication

Revision ID: 20260827_0004
Revises: 20260827_0003
Create Date: 2026-08-27

A rejected sighting is not a signal: it was never retrieved and has no body, so
it gets its own table rather than a row with an invented retrieval time. A
syndicated copy is a signal, keeps its publisher, and points at the copy seen
first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0004"
down_revision: str | None = "20260827_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FILTER_RULE_GROUPS = ("title_exclusion", "domain_blocklist")

PROCESSING_STATUSES = (
    "fetched",
    "normalized",
    "classified",
    "extracted",
    "geocoded",
    "matched",
    "published",
    "duplicate",
    "failed",
    "needs_review",
)

PREVIOUS_PROCESSING_STATUSES = tuple(
    status for status in PROCESSING_STATUSES if status != "duplicate"
)


def _values(statuses: tuple[str, ...]) -> str:
    return ", ".join(f"'{status}'" for status in statuses)


def upgrade() -> None:
    op.create_table(
        "filter_rules",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "rule_group",
            sa.Enum(
                *FILTER_RULE_GROUPS,
                name="filter_rule_group_values",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_filter_rules"),
        sa.UniqueConstraint("rule_group", "pattern", name="uq_filter_rules_rule_group"),
    )

    op.create_table(
        "rejected_sightings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("gdelt_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filter_rule_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rejected_sightings"),
        sa.UniqueConstraint("canonical_url", name="uq_rejected_sightings_canonical_url"),
        sa.ForeignKeyConstraint(
            ["filter_rule_id"],
            ["filter_rules.id"],
            name="fk_rejected_sightings_filter_rule_id_filter_rules",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_rejected_sightings_filter_rule_id", "rejected_sightings", ["filter_rule_id"])
    op.create_index("ix_rejected_sightings_rejected_at", "rejected_sightings", ["rejected_at"])

    op.add_column("signals", sa.Column("duplicate_of_signal_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_signals_duplicate_of_signal_id_signals",
        "signals",
        "signals",
        ["duplicate_of_signal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_signals_duplicate_of_signal_id", "signals", ["duplicate_of_signal_id"])

    # The vocabulary is a check constraint over values, not a native enum, so
    # widening it means replacing the constraint.
    op.drop_constraint("ck_signals_processing_status_values", "signals", type_="check")
    op.create_check_constraint(
        "processing_status_values",
        "signals",
        f"processing_status IN ({_values(PROCESSING_STATUSES)})",
    )


def downgrade() -> None:
    # Nothing may be left in the value about to disappear.
    op.execute("UPDATE signals SET processing_status = 'fetched' WHERE processing_status = 'duplicate'")
    op.drop_constraint("ck_signals_processing_status_values", "signals", type_="check")
    op.create_check_constraint(
        "processing_status_values",
        "signals",
        f"processing_status IN ({_values(PREVIOUS_PROCESSING_STATUSES)})",
    )

    op.drop_index("ix_signals_duplicate_of_signal_id", table_name="signals")
    op.drop_constraint("fk_signals_duplicate_of_signal_id_signals", "signals", type_="foreignkey")
    op.drop_column("signals", "duplicate_of_signal_id")

    op.drop_index("ix_rejected_sightings_rejected_at", table_name="rejected_sightings")
    op.drop_index("ix_rejected_sightings_filter_rule_id", table_name="rejected_sightings")
    op.drop_table("rejected_sightings")
    # No explicit constraint drop: the check constraint lives on the table and
    # goes with it.
    op.drop_table("filter_rules")
```

- [ ] **Step 2: Verify the constraint name before trusting the drop**

The name `ck_signals_processing_status_values` comes from the naming convention `ck_%(table_name)s_%(constraint_name)s` in `db/base.py` applied to the vocabulary name `processing_status_values`. Confirm it against the live database:

```bash
uv run --package episignal-api python -c "from sqlalchemy import inspect; from episignal_backend.db.session import get_engine; print([c['name'] for c in inspect(get_engine()).get_check_constraints('signals')])"
```

Expected: a list containing `ck_signals_processing_status_values`. If the name differs, correct both `drop_constraint` calls in the migration before continuing.

- [ ] **Step 3: Apply the migration**

Run: `pnpm db:migrate`
Expected: `Running upgrade 20260827_0003 -> 20260827_0004`

- [ ] **Step 4: Verify the round trip**

```bash
pnpm db:rollback
pnpm db:migrate
```

Expected: both complete without error. The rollback proves the downgrade path works before anything depends on it.

- [ ] **Step 5: Commit**

```bash
git add database/migrations/versions/20260827_0004_stage0_filtering.py
git commit -m "feat: migrate the Stage 0 filtering and deduplication schema"
```

---

## Task 5: The relevance filter

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/filtering.py`
- Test: `packages/backend/tests/test_filtering.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_filtering.py`:

```python
from datetime import UTC, datetime
from uuid import uuid4

from episignal_backend.db.types import FilterRuleGroup
from episignal_backend.ingestion.documents import DiscoveredArticle, FilterRule
from episignal_backend.ingestion.filtering import compile_rules, evaluate

SEEN = datetime(2026, 8, 27, 7, 45, tzinfo=UTC)

VIOLENCE = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.TITLE_EXCLUSION,
    pattern=r"\boutbreak of (violence|unrest)\b",
    label="Outbreak of violence",
)
WIRE = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.DOMAIN_BLOCKLIST,
    pattern="prnewswire.com",
    label="Press release wire",
)
BROKEN = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.TITLE_EXCLUSION,
    pattern=r"([unclosed",
    label="Broken rule",
)


def article(title: str, domain: str = "example.vn") -> DiscoveredArticle:
    return DiscoveredArticle(
        url=f"https://{domain}/story",
        canonical_url=f"https://{domain}/story",
        title=title,
        domain=domain,
        gdelt_seen_at=SEEN,
    )


def test_a_metaphorical_title_is_rejected() -> None:
    rules = compile_rules((VIOLENCE,))

    assert evaluate(article("Outbreak of violence in the capital"), rules) is VIOLENCE


def test_matching_ignores_case() -> None:
    rules = compile_rules((VIOLENCE,))

    assert evaluate(article("OUTBREAK OF UNREST grips the city"), rules) is VIOLENCE


def test_a_real_outbreak_report_is_kept() -> None:
    rules = compile_rules((VIOLENCE, WIRE))

    assert evaluate(article("Measles outbreak spreads in Pennsylvania"), rules) is None


def test_an_article_with_no_rules_is_kept() -> None:
    rules = compile_rules(())

    assert evaluate(article("Anything at all"), rules) is None


def test_a_blocklisted_domain_is_rejected() -> None:
    rules = compile_rules((WIRE,))

    assert evaluate(article("Vaccine maker reports results", "prnewswire.com"), rules) is WIRE


def test_a_subdomain_of_a_blocklisted_domain_is_rejected() -> None:
    rules = compile_rules((WIRE,))

    assert evaluate(article("Vaccine maker reports", "www.prnewswire.com"), rules) is WIRE


def test_a_lookalike_domain_is_kept() -> None:
    rules = compile_rules((WIRE,))

    assert evaluate(article("Cholera cases rise", "notprnewswire.com"), rules) is None


def test_an_invalid_pattern_is_skipped_without_failing_the_run() -> None:
    rules = compile_rules((BROKEN, VIOLENCE))

    assert rules.invalid == 1
    assert evaluate(article("Outbreak of violence in the capital"), rules) is VIOLENCE
    assert evaluate(article("Dengue cases double"), rules) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_filtering.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ingestion.filtering'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ingestion/filtering.py`:

```python
"""Stage 0, gate one: decide whether an article is worth fetching.

Negative-only by design. An article is rejected when it matches an explicit
exclusion and never for failing to prove itself relevant, because a wrongly
rejected article leaves no body, no extraction and no signal, and nothing
downstream can notice it is missing. A wrongly kept article costs one page
fetch.

This module imports neither SQLAlchemy nor httpx.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.db.types import FilterRuleGroup
from episignal_backend.ingestion.documents import DiscoveredArticle, FilterRule

logger = logging.getLogger("episignal_backend.ingestion.filtering")


@dataclass(frozen=True)
class CompiledRules:
    """Rules prepared once per run.

    `invalid` counts the patterns that would not compile. They are skipped
    rather than raised: one malformed rule must not silence the rest.
    """

    titles: tuple[tuple[re.Pattern[str], FilterRule], ...] = ()
    domains: tuple[tuple[str, FilterRule], ...] = ()
    invalid: int = 0


def compile_rules(rules: Sequence[FilterRule]) -> CompiledRules:
    titles: list[tuple[re.Pattern[str], FilterRule]] = []
    domains: list[tuple[str, FilterRule]] = []
    invalid = 0

    for rule in rules:
        if rule.rule_group is FilterRuleGroup.DOMAIN_BLOCKLIST:
            # A host, never a regular expression: a dot in a domain is a literal
            # separator, and treating it as "any character" would reject
            # lookalikes the rule never named.
            domains.append((rule.pattern.strip().lower(), rule))
            continue
        try:
            titles.append((re.compile(rule.pattern, re.IGNORECASE), rule))
        except re.error:
            invalid += 1
            logger.warning("Filter rule %s has an invalid pattern and was skipped", rule.label)

    return CompiledRules(titles=tuple(titles), domains=tuple(domains), invalid=invalid)


def evaluate(article: DiscoveredArticle, rules: CompiledRules) -> FilterRule | None:
    """Return the rule that rejects this article, or None to keep it."""
    for blocked, rule in rules.domains:
        # Exact host or dotted suffix, so example.com covers news.example.com
        # but never notexample.com.
        if article.domain == blocked or article.domain.endswith(f".{blocked}"):
            return rule

    for pattern, rule in rules.titles:
        if pattern.search(article.title):
            return rule

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_filtering.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/filtering.py packages/backend/tests/test_filtering.py
git commit -m "feat: decide which discovered articles are worth fetching"
```

---

## Task 6: Title and body similarity

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/similarity.py`
- Create: `packages/backend/tests/fixtures/syndicated_body_a.txt`
- Create: `packages/backend/tests/fixtures/syndicated_body_b.txt`
- Create: `packages/backend/tests/fixtures/independent_body.txt`
- Test: `packages/backend/tests/test_similarity.py`

The two real titles in `packages/backend/tests/fixtures/gdelt_artlist.json` are the reference case:

```text
Dos residentes no vacunados mueren de sarampion en Pensilvania - Telemundo Dallas ( 39 )
Dos residentes no vacunados mueren de sarampion en Pensilvania - Telemundo New York ( 47 )
```

They must normalize to the same token set. The third fixture title must not be damaged by the same rule:

```text
How a near - fatal illness inspired a Highlander musical voyage
```

That title contains a spaced hyphen inside the headline itself. Dropping everything after the last spaced dash would truncate it to `How a near`. The rule is therefore: drop the tail only when it is short, because publisher furniture is short and a headline clause is not. `Telemundo New York ( 47 )` is six whitespace-separated tokens; `fatal illness inspired a Highlander musical voyage` is seven.

- [ ] **Step 1: Create the body fixtures**

Create `packages/backend/tests/fixtures/syndicated_body_a.txt`:

```text
Two unvaccinated residents of Pennsylvania have died of measles, state health
officials confirmed on Monday. Both patients were adults who had not received
any dose of the measles, mumps and rubella vaccine, the Department of Health
said in a statement. The department reported a total of forty-one confirmed
cases across three counties since the beginning of July. Health officials urged
residents to check their vaccination records and said walk-in clinics would open
in the affected counties this week.
```

Create `packages/backend/tests/fixtures/syndicated_body_b.txt` — the same wire copy carrying a different affiliate's boilerplate, which is exactly the case an exact hash misses:

```text
Two unvaccinated residents of Pennsylvania have died of measles, state health
officials confirmed on Monday. Both patients were adults who had not received
any dose of the measles, mumps and rubella vaccine, the Department of Health
said in a statement. The department reported a total of forty-one confirmed
cases across three counties since the beginning of July. Health officials urged
residents to check their vaccination records and said walk-in clinics would open
in the affected counties this week. Follow Telemundo New York for local news and
weather updates.
```

The boilerplate is deliberately short. Body B strictly extends body A, so every
shingle of A appears in B and their Jaccard similarity is `shingles(A) /
shingles(B)`. At roughly 78 words against 88, that is about 0.88, comfortably
clear of the 0.80 threshold. A long tail would drag it under and the test would
fail for a reason that has nothing to do with the rule being tested.

Create `packages/backend/tests/fixtures/independent_body.txt` — a different newsroom writing up the same event, which must survive as its own signal:

```text
Pennsylvania has recorded its first measles deaths in more than a decade. The
two people who died were adults, and neither had been immunised, according to a
briefing given by the state health secretary on Monday afternoon. Local doctors
described a rise in enquiries about vaccination since the deaths were reported.
The state has counted several dozen infections this summer, concentrated in
communities with low childhood immunisation coverage, and has asked schools to
review their records before the new term begins.
```

- [ ] **Step 2: Write the failing test**

Create `packages/backend/tests/test_similarity.py`:

```python
import json
from pathlib import Path

from episignal_backend.ingestion.similarity import (
    body_similarity,
    normalize_title,
    title_similarity,
)

FIXTURES = Path(__file__).parent / "fixtures"
SHINGLE_SIZE = 5


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def gdelt_titles() -> list[str]:
    payload = json.loads(read("gdelt_artlist.json"))
    return [article["title"] for article in payload["articles"]]


def test_affiliate_furniture_is_dropped_from_a_syndicated_title() -> None:
    first, second, _ = gdelt_titles()

    assert normalize_title(first) == normalize_title(second)


def test_two_syndicated_titles_are_identical_after_normalization() -> None:
    first, second, _ = gdelt_titles()

    assert title_similarity(first, second) == 1.0


def test_a_headline_containing_a_spaced_hyphen_is_not_truncated() -> None:
    _, _, scottish = gdelt_titles()

    tokens = normalize_title(scottish)

    assert "voyage" in tokens
    assert "highlander" in tokens


def test_unrelated_titles_are_not_similar() -> None:
    first, _, scottish = gdelt_titles()

    assert title_similarity(first, scottish) < 0.5


def test_syndicated_bodies_are_similar_despite_different_boilerplate() -> None:
    similarity = body_similarity(
        read("syndicated_body_a.txt"), read("syndicated_body_b.txt"), size=SHINGLE_SIZE
    )

    assert similarity >= 0.80


def test_an_independent_report_on_the_same_event_is_not_similar() -> None:
    similarity = body_similarity(
        read("syndicated_body_a.txt"), read("independent_body.txt"), size=SHINGLE_SIZE
    )

    assert similarity < 0.80


def test_an_empty_body_never_matches() -> None:
    assert body_similarity("", "", size=SHINGLE_SIZE) == 0.0
    assert body_similarity("", read("independent_body.txt"), size=SHINGLE_SIZE) == 0.0


def test_a_body_shorter_than_the_shingle_is_compared_whole() -> None:
    assert body_similarity("Cholera in Juba", "Cholera in Juba", size=SHINGLE_SIZE) == 1.0
    assert body_similarity("Cholera in Juba", "Measles in Lima", size=SHINGLE_SIZE) == 0.0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_similarity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ingestion.similarity'`

- [ ] **Step 4: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ingestion/similarity.py`:

```python
"""Stage 0, gate two: how alike two stored documents are.

Deterministic and explainable on purpose. Embeddings would answer the same
question with a model call, and this stage exists to run before any model call.
Exact set arithmetic rather than MinHash or SimHash: the candidate window holds
at most low thousands of rows, so an approximation would save nothing and would
make "why were these two merged" harder to answer.

This module imports neither SQLAlchemy nor httpx.
"""

import re
import unicodedata

# A spaced dash, in any of the three widths a publisher might use.
SEPARATOR = re.compile(r"\s[-–—]\s")
PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)

# Publisher furniture is short: "Telemundo New York ( 47 )" is six tokens. A
# longer tail is part of the headline, as in "How a near - fatal illness
# inspired a Highlander musical voyage", and truncating it would throw away most
# of the title.
FURNITURE_MAX_WORDS = 6


def drop_furniture(title: str) -> str:
    matches = list(SEPARATOR.finditer(title))
    if not matches:
        return title

    last = matches[-1]
    tail = title[last.end() :]
    if len(tail.split()) > FURNITURE_MAX_WORDS:
        return title
    return title[: last.start()]


def normalize_title(title: str) -> frozenset[str]:
    folded = unicodedata.normalize("NFC", title).casefold()
    stripped = PUNCTUATION.sub(" ", drop_furniture(folded))
    return frozenset(stripped.split())


def shingles(body: str, size: int) -> frozenset[str]:
    words = unicodedata.normalize("NFC", body).casefold().split()
    if not words:
        return frozenset()
    if len(words) < size:
        # Too short to shingle. Comparing it whole is honest; padding it would
        # invent overlap that the text does not have.
        return frozenset({" ".join(words)})
    return frozenset(
        " ".join(words[index : index + size]) for index in range(len(words) - size + 1)
    )


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    # Two empty sets are not a perfect match. Nothing in common with nothing is
    # no evidence of syndication, and returning 1.0 would merge every stub.
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def title_similarity(left: str, right: str) -> float:
    return jaccard(normalize_title(left), normalize_title(right))


def body_similarity(left: str, right: str, *, size: int) -> float:
    return jaccard(shingles(left, size), shingles(right, size))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_similarity.py -v`
Expected: PASS, 8 tests

If `test_syndicated_bodies_are_similar_despite_different_boilerplate` fails just under the threshold, do **not** lower the threshold to make it pass. Read the two fixtures: the shared text must dominate. Lengthen the shared portion of the fixtures rather than weakening the rule the product depends on.

- [ ] **Step 6: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/similarity.py packages/backend/tests/test_similarity.py packages/backend/tests/fixtures/syndicated_body_a.txt packages/backend/tests/fixtures/syndicated_body_b.txt packages/backend/tests/fixtures/independent_body.txt
git commit -m "feat: measure title and body similarity between stored documents"
```

---

## Task 7: The seeded rule library

**Files:**
- Create: `database/seeds/filter_rules.json`
- Modify: `packages/backend/src/episignal_backend/seeds.py`
- Test: `packages/backend/tests/test_seeds.py`

- [ ] **Step 1: Write the seed file**

Create `database/seeds/filter_rules.json`. Every rule here is negative and narrow. The domain blocklist is deliberately tiny: each entry silences a whole publisher, so an addition needs a stronger justification than a title pattern does.

```json
[
  {
    "rule_group": "title_exclusion",
    "pattern": "\\boutbreak of (violence|war|fighting|unrest|protests?|riots?|crime)\\b",
    "label": "Outbreak of violence"
  },
  {
    "rule_group": "title_exclusion",
    "pattern": "\\bepidemic of (violence|loneliness|misinformation|debt|hate|fraud|burglaries)\\b",
    "label": "Epidemic as metaphor"
  },
  {
    "rule_group": "title_exclusion",
    "pattern": "\\bplague of (locusts|rats|mice|potholes|scandals)\\b",
    "label": "Plague as metaphor"
  },
  {
    "rule_group": "title_exclusion",
    "pattern": "\\bviral (video|photo|post|tweet|clip|moment|sensation)\\b",
    "label": "Viral content"
  },
  {
    "rule_group": "title_exclusion",
    "pattern": "\\b(injury|injuries) (epidemic|outbreak|crisis)\\b",
    "label": "Sports injury metaphor"
  },
  {
    "rule_group": "title_exclusion",
    "pattern": "\\bfever pitch\\b",
    "label": "Fever pitch metaphor"
  },
  {
    "rule_group": "title_exclusion",
    "pattern": "\\b(1918|1919) (flu|influenza|pandemic)\\b",
    "label": "1918 pandemic retrospective"
  },
  {
    "rule_group": "title_exclusion",
    "pattern": "\\b(movie|film|series|episode|trailer|box office)\\b.*\\b(outbreak|contagion|pandemic|zombie|virus)\\b",
    "label": "Entertainment coverage"
  },
  {
    "rule_group": "title_exclusion",
    "pattern": "\\b(shares?|stocks?|earnings|ipo|dividend)\\b.*\\b(vaccine|pharma|biotech)\\b",
    "label": "Pharmaceutical market coverage"
  },
  {
    "rule_group": "domain_blocklist",
    "pattern": "prnewswire.com",
    "label": "PR Newswire"
  },
  {
    "rule_group": "domain_blocklist",
    "pattern": "globenewswire.com",
    "label": "GlobeNewswire"
  },
  {
    "rule_group": "domain_blocklist",
    "pattern": "businesswire.com",
    "label": "Business Wire"
  }
]
```

- [ ] **Step 2: Write the failing test**

Append to `packages/backend/tests/test_seeds.py`:

```python
def test_filter_rules_load_and_are_all_negative() -> None:
    from episignal_backend.db.types import FilterRuleGroup
    from episignal_backend.seeds import load_filter_rules

    rules = load_filter_rules()

    assert len(rules) >= 10
    assert any(rule.rule_group is FilterRuleGroup.DOMAIN_BLOCKLIST for rule in rules)
    assert all(rule.pattern.strip() for rule in rules)


def test_every_seeded_title_pattern_compiles() -> None:
    import re

    from episignal_backend.db.types import FilterRuleGroup
    from episignal_backend.seeds import load_filter_rules

    for rule in load_filter_rules():
        if rule.rule_group is FilterRuleGroup.TITLE_EXCLUSION:
            re.compile(rule.pattern)


def test_no_seeded_rule_would_reject_a_real_outbreak_headline() -> None:
    from episignal_backend.ingestion.filtering import compile_rules, evaluate
    from episignal_backend.ingestion.documents import DiscoveredArticle, FilterRule
    from datetime import UTC, datetime

    from episignal_backend.seeds import load_filter_rules

    rules = compile_rules(
        tuple(
            FilterRule(rule_group=seed.rule_group, pattern=seed.pattern, label=seed.label)
            for seed in load_filter_rules()
        )
    )
    headlines = (
        "Measles outbreak spreads in Pennsylvania",
        "Cholera cases double in Juba after floods",
        "Health ministry confirms H5N1 in poultry workers",
        "Dos residentes no vacunados mueren de sarampion en Pensilvania",
        "Eighteen students hospitalised with unknown fever",
    )
    for headline in headlines:
        article = DiscoveredArticle(
            url="https://example.org/a",
            canonical_url="https://example.org/a",
            title=headline,
            domain="example.org",
            gdelt_seen_at=datetime(2026, 8, 27, 7, 45, tzinfo=UTC),
        )
        assert evaluate(article, rules) is None, headline
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_seeds.py -k filter -v`
Expected: FAIL with `ImportError: cannot import name 'load_filter_rules'`

- [ ] **Step 4: Write minimal implementation**

In `packages/backend/src/episignal_backend/seeds.py`, extend the imports:

```python
from episignal_backend.db.types import CredibilityTier, FilterRuleGroup, SourceType
from episignal_backend.models import (
    Disease,
    GdeltQueryRule,
    SignalFilterRule,
    Source,
)
```

Add the seed model after `QueryRuleSeed`:

```python
class FilterRuleSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_group: FilterRuleGroup
    pattern: str = Field(min_length=1)
    label: str = Field(min_length=1)
    active: bool = True
```

Extend `SeedResult`:

```python
@dataclass(frozen=True)
class SeedResult:
    diseases: int
    sources: int
    query_rules: int
    filter_rules: int
```

Add the loader after `load_query_rules`:

```python
def load_filter_rules() -> tuple[FilterRuleSeed, ...]:
    return tuple(TypeAdapter(list[FilterRuleSeed]).validate_python(_read_seed("filter_rules.json")))
```

Widen the `_upsert` signature to accept the new model:

```python
def _upsert(
    session: Session,
    model: type[Disease] | type[Source] | type[GdeltQueryRule] | type[SignalFilterRule],
    rows: list[dict[str, Any]],
    natural_key: tuple[str, ...],
) -> None:
```

Extend `seed_database`:

```python
def seed_database(session: Session) -> SeedResult:
    diseases = load_diseases()
    sources = load_sources()
    query_rules = load_query_rules()
    filter_rules = load_filter_rules()
    _upsert(session, Disease, [item.model_dump() for item in diseases], ("slug",))
    _upsert(session, Source, [item.model_dump() for item in sources], ("name",))
    _upsert(
        session,
        GdeltQueryRule,
        [item.model_dump() for item in query_rules],
        ("query", "language"),
    )
    _upsert(
        session,
        SignalFilterRule,
        [item.model_dump() for item in filter_rules],
        ("rule_group", "pattern"),
    )
    return SeedResult(
        diseases=len(diseases),
        sources=len(sources),
        query_rules=len(query_rules),
        filter_rules=len(filter_rules),
    )
```

- [ ] **Step 5: Update the seed runner output**

In `packages/backend/src/episignal_backend/seed_runner.py`, replace this line:

```python
    print(f"diseases={result.diseases} sources={result.sources} query_rules={result.query_rules}")
```

with:

```python
    print(
        f"diseases={result.diseases} sources={result.sources} "
        f"query_rules={result.query_rules} filter_rules={result.filter_rules}"
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_seeds.py -v`
Expected: PASS, including the three new tests

- [ ] **Step 7: Seed the database and confirm idempotence**

```bash
pnpm db:seed
pnpm db:seed
```

Expected: both runs print the same counts, ending `filter_rules=12`. Running twice proves the upsert does not duplicate.

- [ ] **Step 8: Commit**

```bash
git add database/seeds/filter_rules.json packages/backend/src/episignal_backend/seeds.py packages/backend/src/episignal_backend/seed_runner.py packages/backend/tests/test_seeds.py
git commit -m "feat: seed the Stage 0 filter rule library"
```

---

## Task 8: Storage for rules and rejections

**Files:**
- Modify: `packages/backend/src/episignal_backend/ingestion/protocol.py`
- Modify: `packages/backend/src/episignal_backend/ingestion/repository.py`
- Test: `packages/backend/tests/test_discovery_repository.py`

- [ ] **Step 1: Write the failing test**

The `FakeSession` in this file takes a list of raw values and wraps each in a `FakeResult` itself, so pass `[[row]]`, not `[FakeResult([row])]`. `FakeResult` currently exposes `scalar_one_or_none`, `scalar_one`, and `all`, but `filter_rules` calls `.scalars()`. Add that one method to the existing `FakeResult` class:

```python
    def scalars(self) -> Any:
        return self._value
```

Then append the tests:

```python
def test_active_filter_rules_are_returned_as_contracts() -> None:
    from episignal_backend.db.types import FilterRuleGroup
    from episignal_backend.models import SignalFilterRule

    row = SignalFilterRule(
        rule_group=FilterRuleGroup.TITLE_EXCLUSION,
        pattern=r"\bviral video\b",
        label="Viral content",
        active=True,
    )
    row.id = uuid4()
    session = FakeSession([[row]])
    repository = SqlAlchemyDiscoveryRepository(session)

    rules = repository.filter_rules()

    assert len(rules) == 1
    assert rules[0].pattern == r"\bviral video\b"
    assert rules[0].rule_group is FilterRuleGroup.TITLE_EXCLUSION
    assert rules[0].id == row.id


def test_recording_a_rejection_issues_one_statement() -> None:
    from episignal_backend.ingestion.documents import Rejection

    session = FakeSession([])
    repository = SqlAlchemyDiscoveryRepository(session)

    repository.record_rejection(
        Rejection(
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            title="Outbreak of violence in the capital",
            domain="example.com",
            gdelt_seen_at=SEEN,
            rejected_at=NOW,
            filter_rule_id=uuid4(),
        )
    )

    assert len(session.executed) == 1


def test_the_repository_satisfies_the_discovery_protocol() -> None:
    session = FakeSession([])

    assert isinstance(SqlAlchemyDiscoveryRepository(session), DiscoveryRepository)
```

`FakeSession` already records every statement in `self.executed`, so no other change to it is needed.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_discovery_repository.py -k "filter_rules or rejection" -v`
Expected: FAIL with `AttributeError: 'SqlAlchemyDiscoveryRepository' object has no attribute 'filter_rules'`

- [ ] **Step 3: Add the Protocol methods**

In `packages/backend/src/episignal_backend/ingestion/protocol.py`, extend the documents import:

```python
from episignal_backend.ingestion.documents import (
    ComparableSignal,
    DiscoveredArticle,
    DiscoveredSignal,
    FilterRule,
    NormalizedSignal,
    Publisher,
    QueryRule,
    RawDocument,
    Rejection,
    StubRetrieval,
    TimeWindow,
)
```

Add two methods to `DiscoveryRepository`, immediately after `active_rules`:

```python
    def filter_rules(self) -> Sequence[FilterRule]: ...

    def record_rejection(self, rejection: Rejection) -> None: ...
```

- [ ] **Step 4: Implement them**

In `packages/backend/src/episignal_backend/ingestion/repository.py`, extend the imports:

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

from episignal_backend.ingestion.documents import (
    ComparableSignal,
    DiscoveredArticle,
    DiscoveredSignal,
    FilterRule,
    NormalizedSignal,
    Publisher,
    QueryRule,
    Rejection,
    StubRetrieval,
)
from episignal_backend.models import (
    GdeltQueryRule,
    RejectedSighting,
    Signal,
    SignalFilterRule,
    Source,
)
```

Add both methods to `SqlAlchemyDiscoveryRepository`, after `active_rules`:

```python
    def filter_rules(self) -> Sequence[FilterRule]:
        rows = self._session.execute(
            select(SignalFilterRule)
            .where(SignalFilterRule.active.is_(True))
            .order_by(SignalFilterRule.rule_group, SignalFilterRule.label)
        ).scalars()
        return tuple(
            FilterRule(
                id=row.id,
                rule_group=row.rule_group,
                pattern=row.pattern,
                label=row.label,
            )
            for row in rows
        )

    def record_rejection(self, rejection: Rejection) -> None:
        # Conflict-do-nothing: the same article is sighted in several
        # consecutive windows, and one row per article is the useful record.
        statement = (
            pg_insert(RejectedSighting)
            .values(
                url=rejection.url,
                canonical_url=rejection.canonical_url,
                title=rejection.title,
                domain=rejection.domain,
                gdelt_seen_at=rejection.gdelt_seen_at,
                rejected_at=rejection.rejected_at,
                filter_rule_id=rejection.filter_rule_id,
            )
            .on_conflict_do_nothing(index_elements=[RejectedSighting.canonical_url])
        )
        self._session.execute(statement)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_discovery_repository.py -v`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/protocol.py packages/backend/src/episignal_backend/ingestion/repository.py packages/backend/tests/test_discovery_repository.py
git commit -m "feat: store filter rules and rejected sightings"
```

---

## Task 9: Gate one inside the discovery run

**Files:**
- Modify: `packages/backend/src/episignal_backend/ingestion/discovery.py`
- Test: `packages/backend/tests/test_discovery_pipeline.py`

- [ ] **Step 1: Extend the fake repository**

In `packages/backend/tests/test_discovery_pipeline.py`, add to `FakeRepository.__init__`:

```python
        self.rules: tuple[FilterRule, ...] = ()
        self.rejections: list[Rejection] = []
        self.rejection_fails = False
```

and add two methods to the same class:

```python
    def filter_rules(self) -> Sequence[FilterRule]:
        return self.rules

    def record_rejection(self, rejection: Rejection) -> None:
        if self.rejection_fails:
            raise RuntimeError("rejection table unavailable")
        self.rejections.append(rejection)
```

Extend the imports at the top of the file:

```python
from episignal_backend.db.types import FilterRuleGroup, ProcessingStatus
from episignal_backend.ingestion.documents import (
    DiscoveredArticle,
    DiscoveredSignal,
    FilterRule,
    Publisher,
    QueryRule,
    Rejection,
    TimeWindow,
)
```

- [ ] **Step 2: Write the failing test**

Append to `packages/backend/tests/test_discovery_pipeline.py`:

```python
METAPHOR = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.TITLE_EXCLUSION,
    pattern=r"\boutbreak of violence\b",
    label="Outbreak of violence",
)


def violent(path: str) -> DiscoveredArticle:
    return DiscoveredArticle(
        url=f"https://example.vn{path}",
        canonical_url=f"https://example.vn{path}",
        title="Outbreak of violence in the capital",
        domain="example.vn",
        gdelt_seen_at=SEEN,
        query_rule_id=RULE.id,
    )


def test_a_rejected_article_is_never_fetched() -> None:
    repository = FakeRepository()
    repository.rules = (METAPHOR,)
    connector = FakeConnector(articles=(violent("/a"),))

    result = run_discovery(repository, connector, now=NOW)

    assert connector.retrieved == []
    assert repository.added == []
    assert result.rejected == 1
    assert result.stored == 0


def test_a_rejection_names_the_rule_that_caused_it() -> None:
    repository = FakeRepository()
    repository.rules = (METAPHOR,)
    connector = FakeConnector(articles=(violent("/a"),))

    run_discovery(repository, connector, now=NOW)

    assert len(repository.rejections) == 1
    assert repository.rejections[0].filter_rule_id == METAPHOR.id
    assert repository.rejections[0].canonical_url == "https://example.vn/a"
    assert repository.rejections[0].gdelt_seen_at == SEEN


def test_a_kept_article_is_still_fetched_and_stored() -> None:
    repository = FakeRepository()
    repository.rules = (METAPHOR,)
    connector = FakeConnector(articles=(article("/a"), violent("/b")))

    result = run_discovery(repository, connector, now=NOW)

    assert connector.retrieved == ["https://example.vn/a"]
    assert result.stored == 1
    assert result.rejected == 1


def test_filtering_runs_before_the_per_run_cap() -> None:
    repository = FakeRepository()
    repository.rules = (METAPHOR,)
    connector = FakeConnector(articles=(violent("/a"), article("/b")))

    result = run_discovery(repository, connector, now=NOW, max_articles=1)

    # The one slot goes to the article worth having, not to the one about to be
    # thrown away.
    assert connector.retrieved == ["https://example.vn/b"]
    assert result.deferred == 0


def test_an_invalid_rule_is_counted_and_does_not_stop_the_run() -> None:
    repository = FakeRepository()
    repository.rules = (
        FilterRule(
            id=uuid4(),
            rule_group=FilterRuleGroup.TITLE_EXCLUSION,
            pattern=r"([unclosed",
            label="Broken",
        ),
    )
    connector = FakeConnector(articles=(article("/a"),))

    result = run_discovery(repository, connector, now=NOW)

    assert result.rules_invalid == 1
    assert result.stored == 1


def test_an_article_survives_when_its_rejection_cannot_be_recorded() -> None:
    repository = FakeRepository()
    repository.rules = (METAPHOR,)
    repository.rejection_fails = True
    connector = FakeConnector(articles=(violent("/a"),))

    result = run_discovery(repository, connector, now=NOW)

    # A lost audit row must not also lose the article.
    assert connector.retrieved == ["https://example.vn/a"]
    assert result.failed == 1
    assert result.rejected == 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_discovery_pipeline.py -k "rejected or rejection or cap or invalid_rule" -v`
Expected: FAIL with `AttributeError: 'DiscoveryResult' object has no attribute 'rejected'`

- [ ] **Step 4: Write minimal implementation**

In `packages/backend/src/episignal_backend/ingestion/discovery.py`, extend the imports:

```python
from episignal_backend.ingestion.documents import DiscoveredArticle, Rejection, TimeWindow
from episignal_backend.ingestion.filtering import compile_rules, evaluate
```

Add two fields to `DiscoveryResult`, after `duplicate`:

```python
@dataclass(frozen=True)
class DiscoveryResult:
    rules_run: int = 0
    rules_failed: int = 0
    rules_invalid: int = 0
    discovered: int = 0
    duplicate: int = 0
    rejected: int = 0
    deferred: int = 0
    stored: int = 0
    needs_review: int = 0
    failed: int = 0
```

In `run_discovery`, load the filter rules alongside the query rules. Replace:

```python
    rules = repository.active_rules()
    rules_failed = 0
```

with:

```python
    rules = repository.active_rules()
    filters = compile_rules(repository.filter_rules())
    if not filters.titles and not filters.domains:
        # A valid configuration, not an error. Said out loud because the
        # alternative reading — a seeding accident — looks identical from the
        # counts alone.
        logger.info("No active filter rules; discovery is running unfiltered")
    rules_failed = 0
    failed = 0
```

Then replace the block that builds `candidates` and `selected`:

```python
    already_stored = repository.seen_urls(tuple(discovered))
    candidates = [
        article
        for canonical_url, article in discovered.items()
        if canonical_url not in already_stored
    ]
    # Oldest first, so a burst of fresh articles never starves a discovery that
    # has already been waiting for a slot.
    candidates.sort(key=lambda article: article.gdelt_seen_at)
    selected = candidates[:max_articles]

    stored = 0
    needs_review = 0
    failed = 0
```

with:

```python
    already_stored = repository.seen_urls(tuple(discovered))
    surviving = [
        article
        for canonical_url, article in discovered.items()
        if canonical_url not in already_stored
    ]

    # Gate one. Before the cap, so the run's budget is spent on articles worth
    # having rather than on articles about to be discarded.
    candidates: list[DiscoveredArticle] = []
    rejected = 0
    for article in surviving:
        rule = evaluate(article, filters)
        if rule is None:
            candidates.append(article)
            continue
        try:
            repository.record_rejection(
                Rejection(
                    url=article.url,
                    canonical_url=article.canonical_url,
                    title=article.title,
                    domain=article.domain,
                    gdelt_seen_at=article.gdelt_seen_at,
                    rejected_at=moment,
                    filter_rule_id=rule.id,
                )
            )
            repository.commit()
        except Exception as error:
            repository.rollback()
            failed += 1
            # Keep it: losing the audit row must not also lose the article.
            candidates.append(article)
            logger.error(
                "Could not record the rejection of %s (%s)",
                article.canonical_url,
                type(error).__name__,
            )
            continue
        rejected += 1
        logger.info("Rejected %s (%s)", article.canonical_url, rule.label)

    # Oldest first, so a burst of fresh articles never starves a discovery that
    # has already been waiting for a slot.
    candidates.sort(key=lambda article: article.gdelt_seen_at)
    selected = candidates[:max_articles]

    stored = 0
    needs_review = 0
```

Finally extend the returned result:

```python
    return DiscoveryResult(
        rules_run=len(rules),
        rules_failed=rules_failed,
        rules_invalid=filters.invalid,
        discovered=len(discovered),
        duplicate=len(already_stored),
        rejected=rejected,
        deferred=len(candidates) - len(selected),
        stored=stored,
        needs_review=needs_review,
        failed=failed,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_discovery_pipeline.py -v`
Expected: PASS, including the existing tests unchanged

- [ ] **Step 6: Show the new counters in the runner**

In `packages/backend/src/episignal_backend/discover_runner.py`, replace the second `print` with:

```python
    print(
        f"rules={result.rules_run} rules_failed={result.rules_failed} "
        f"rules_invalid={result.rules_invalid} discovered={result.discovered} "
        f"duplicate={result.duplicate} rejected={result.rejected} "
        f"deferred={result.deferred} stored={result.stored} "
        f"needs_review={result.needs_review} failed={result.failed}"
    )
```

- [ ] **Step 7: Run the runner tests**

Run: `uv run pytest packages/backend/tests/test_discover_runner.py -v`
Expected: PASS. If a test asserts on the exact printed line, update the expectation to the new line.

- [ ] **Step 8: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/discovery.py packages/backend/src/episignal_backend/discover_runner.py packages/backend/tests/test_discovery_pipeline.py packages/backend/tests/test_discover_runner.py
git commit -m "feat: filter discovered articles before fetching their pages"
```

---

## Task 10: The deduplication pass

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/dedupe.py`
- Modify: `packages/backend/src/episignal_backend/ingestion/protocol.py`
- Test: `packages/backend/tests/test_dedupe.py`

- [ ] **Step 1: Add the Protocol**

In `packages/backend/src/episignal_backend/ingestion/protocol.py`, add after `DiscoveryRepository`:

```python
@runtime_checkable
class DedupeRepository(Protocol):
    """The storage boundary for Stage 0's second gate.

    Separate from `DiscoveryRepository` because this pass never discovers, never
    fetches, and never registers a publisher. A pass that reads stored signals
    and writes their status has no business holding a handle that can open a
    GDELT query.
    """

    def pending(self, *, limit: int) -> Sequence[ComparableSignal]: ...

    def candidates(
        self, signal: ComparableSignal, *, window_hours: int
    ) -> Sequence[ComparableSignal]: ...

    def primary_of(self, signal_id: UUID) -> UUID: ...

    def mark_duplicate(self, signal_id: UUID, primary_id: UUID) -> None: ...

    def mark_normalized(self, signal_id: UUID) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
```

- [ ] **Step 2: Write the failing test**

Create `packages/backend/tests/test_dedupe.py`:

```python
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from episignal_backend.ingestion.dedupe import DedupeThresholds, run_dedupe
from episignal_backend.ingestion.documents import ComparableSignal

FIXTURES = Path(__file__).parent / "fixtures"
FIRST = datetime(2026, 8, 25, 19, 0, tzinfo=UTC)
LATER = FIRST + timedelta(hours=2)


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def signal(
    *,
    title: str = "Dos residentes no vacunados mueren de sarampion en Pensilvania",
    body: str | None = None,
    content_hash: str | None = None,
    first_seen_at: datetime = FIRST,
    published_at: datetime | None = None,
    identifier: UUID | None = None,
    duplicate_of: UUID | None = None,
) -> ComparableSignal:
    return ComparableSignal(
        id=identifier or uuid4(),
        canonical_url=f"https://example.com/{uuid4()}",
        title=title,
        raw_text=body or read("syndicated_body_a.txt"),
        content_hash=content_hash or ("a" * 64),
        first_seen_at=first_seen_at,
        published_at=published_at,
        duplicate_of_signal_id=duplicate_of,
    )


class FakeRepository:
    def __init__(
        self,
        queue: Sequence[ComparableSignal] = (),
        pool: Sequence[ComparableSignal] = (),
    ) -> None:
        self.queue = tuple(queue)
        self.pool = tuple(pool)
        self.duplicates: list[tuple[UUID, UUID]] = []
        self.normalized: list[UUID] = []
        self.commits = 0
        self.rollbacks = 0
        self.failing = False

    def pending(self, *, limit: int) -> Sequence[ComparableSignal]:
        return self.queue[:limit]

    def candidates(
        self, signal: ComparableSignal, *, window_hours: int
    ) -> Sequence[ComparableSignal]:
        return tuple(item for item in self.pool if item.id != signal.id)

    def primary_of(self, signal_id: UUID) -> UUID:
        for item in self.pool:
            if item.id == signal_id and item.duplicate_of_signal_id is not None:
                return self.primary_of(item.duplicate_of_signal_id)
        return signal_id

    def mark_duplicate(self, signal_id: UUID, primary_id: UUID) -> None:
        if self.failing:
            raise RuntimeError("write failed")
        self.duplicates.append((signal_id, primary_id))

    def mark_normalized(self, signal_id: UUID) -> None:
        if self.failing:
            raise RuntimeError("write failed")
        self.normalized.append(signal_id)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_a_lone_signal_is_normalized() -> None:
    alone = signal()
    repository = FakeRepository(queue=(alone,), pool=(alone,))

    result = run_dedupe(repository)

    assert repository.normalized == [alone.id]
    assert result.primaries == 1
    assert result.duplicates == 0


def test_an_identical_hash_at_another_url_is_a_duplicate() -> None:
    primary = signal(first_seen_at=FIRST)
    copy = signal(first_seen_at=LATER, title="Something else entirely")
    copy = copy.model_copy(update={"content_hash": primary.content_hash})
    repository = FakeRepository(queue=(copy,), pool=(primary, copy))

    result = run_dedupe(repository)

    assert repository.duplicates == [(copy.id, primary.id)]
    assert result.duplicates == 1


def test_a_syndicated_copy_matches_on_title_and_body() -> None:
    primary = signal(
        title="Dos residentes no vacunados mueren de sarampion en Pensilvania - Telemundo Dallas ( 39 )",
        body=read("syndicated_body_a.txt"),
        content_hash="a" * 64,
        first_seen_at=FIRST,
    )
    copy = signal(
        title="Dos residentes no vacunados mueren de sarampion en Pensilvania - Telemundo New York ( 47 )",
        body=read("syndicated_body_b.txt"),
        content_hash="b" * 64,
        first_seen_at=LATER,
    )
    repository = FakeRepository(queue=(copy,), pool=(primary, copy))

    run_dedupe(repository)

    assert repository.duplicates == [(copy.id, primary.id)]


def test_an_independent_report_sharing_a_headline_is_not_a_duplicate() -> None:
    primary = signal(
        title="Two unvaccinated residents die of measles in Pennsylvania",
        body=read("syndicated_body_a.txt"),
        content_hash="a" * 64,
        first_seen_at=FIRST,
    )
    independent = signal(
        title="Two unvaccinated residents die of measles in Pennsylvania",
        body=read("independent_body.txt"),
        content_hash="b" * 64,
        first_seen_at=LATER,
    )
    repository = FakeRepository(queue=(independent,), pool=(primary, independent))

    run_dedupe(repository)

    assert repository.duplicates == []
    assert repository.normalized == [independent.id]


def test_the_earliest_sighting_is_the_primary() -> None:
    earlier = signal(content_hash="a" * 64, first_seen_at=FIRST)
    later = signal(content_hash="a" * 64, first_seen_at=LATER)
    repository = FakeRepository(queue=(later,), pool=(earlier, later))

    run_dedupe(repository)

    assert repository.duplicates == [(later.id, earlier.id)]


def test_published_at_breaks_a_tie_on_first_seen_at() -> None:
    earlier = signal(content_hash="a" * 64, first_seen_at=FIRST, published_at=FIRST)
    later = signal(content_hash="a" * 64, first_seen_at=FIRST, published_at=LATER)
    repository = FakeRepository(queue=(later,), pool=(earlier, later))

    run_dedupe(repository)

    assert repository.duplicates == [(later.id, earlier.id)]


def test_a_pointer_is_flattened_to_the_terminal_primary() -> None:
    root = signal(content_hash="a" * 64, first_seen_at=FIRST)
    middle = signal(
        content_hash="a" * 64,
        first_seen_at=FIRST + timedelta(hours=1),
        duplicate_of=root.id,
    )
    newest = signal(content_hash="a" * 64, first_seen_at=LATER)
    repository = FakeRepository(queue=(newest,), pool=(middle, newest))

    run_dedupe(repository)

    # middle is the only candidate, but it points at root, so newest must too.
    assert repository.duplicates == [(newest.id, root.id)]


def test_a_write_failure_is_counted_without_abandoning_the_batch() -> None:
    first = signal(content_hash="a" * 64)
    second = signal(content_hash="b" * 64, title="Cholera cases rise in Juba")
    repository = FakeRepository(queue=(first, second), pool=(first, second))
    repository.failing = True

    result = run_dedupe(repository)

    assert result.failed == 2
    assert repository.rollbacks == 2


def test_tightening_the_body_threshold_prevents_a_match() -> None:
    primary = signal(
        title="Dos residentes no vacunados mueren de sarampion en Pensilvania - Telemundo Dallas ( 39 )",
        body=read("syndicated_body_a.txt"),
        content_hash="a" * 64,
        first_seen_at=FIRST,
    )
    copy = signal(
        title="Dos residentes no vacunados mueren de sarampion en Pensilvania - Telemundo New York ( 47 )",
        body=read("syndicated_body_b.txt"),
        content_hash="b" * 64,
        first_seen_at=LATER,
    )
    repository = FakeRepository(queue=(copy,), pool=(primary, copy))

    # The titles still agree exactly, so this isolates the body threshold: at
    # 0.99 the affiliate boilerplate is enough to keep the pair apart.
    run_dedupe(repository, thresholds=DedupeThresholds(title=1.0, body=0.99))

    assert repository.duplicates == []
    assert repository.normalized == [copy.id]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_dedupe.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ingestion.dedupe'`

- [ ] **Step 4: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ingestion/dedupe.py`:

```python
"""Stage 0, gate two: resolve syndicated copies to one primary.

The conservative direction is deliberate. Two outlets reporting the same
outbreak independently are corroboration, which is the raw material of the
evidence score, and merging them deletes that with no trace. Carrying a
duplicate that should have been merged is visible and correctable, so a match
requires agreement on both the title and the body.

This module imports neither SQLAlchemy nor httpx.
"""

import logging
from dataclasses import dataclass

from episignal_backend.ingestion.documents import ComparableSignal
from episignal_backend.ingestion.protocol import DedupeRepository
from episignal_backend.ingestion.similarity import body_similarity, title_similarity

DEFAULT_WINDOW_HOURS = 72
DEFAULT_BATCH_SIZE = 200

logger = logging.getLogger("episignal_backend.ingestion.dedupe")


@dataclass(frozen=True)
class DedupeThresholds:
    title: float = 0.90
    body: float = 0.80
    shingle_size: int = 5


@dataclass(frozen=True)
class DedupeResult:
    examined: int = 0
    primaries: int = 0
    duplicates: int = 0
    failed: int = 0


def precedes(left: ComparableSignal, right: ComparableSignal) -> bool:
    """A total order, so the choice of primary is stable and cycles impossible.

    Earliest sighting first: the radar exists to measure detection lead time, so
    the row that earned the lead keeps it. Publisher credibility cannot break
    the tie, because every GDELT-registered publisher starts as unknown.
    """
    if left.first_seen_at != right.first_seen_at:
        return left.first_seen_at < right.first_seen_at
    if left.published_at != right.published_at:
        if left.published_at is None:
            return False
        if right.published_at is None:
            return True
        return left.published_at < right.published_at
    return str(left.id) < str(right.id)


def matches(
    signal: ComparableSignal, candidate: ComparableSignal, thresholds: DedupeThresholds
) -> bool:
    if candidate.content_hash == signal.content_hash:
        return True
    # Title first: it is far cheaper, and a body comparison that the title
    # already rules out is work no pair needs.
    if title_similarity(signal.title, candidate.title) < thresholds.title:
        return False
    similarity = body_similarity(
        signal.raw_text, candidate.raw_text, size=thresholds.shingle_size
    )
    return similarity >= thresholds.body


def run_dedupe(
    repository: DedupeRepository,
    *,
    thresholds: DedupeThresholds | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> DedupeResult:
    limits = thresholds or DedupeThresholds()
    pending = repository.pending(limit=batch_size)

    primaries = 0
    duplicates = 0
    failed = 0

    for signal in pending:
        try:
            primary: ComparableSignal | None = None
            for candidate in repository.candidates(signal, window_hours=window_hours):
                if candidate.id == signal.id:
                    continue
                if not matches(signal, candidate, limits):
                    continue
                if primary is None or precedes(candidate, primary):
                    primary = candidate

            if primary is not None and precedes(primary, signal):
                # Flatten: a pointer must never lead to another pointer, or
                # reading the family back would need a recursive query.
                repository.mark_duplicate(signal.id, repository.primary_of(primary.id))
                duplicates += 1
            else:
                repository.mark_normalized(signal.id)
                primaries += 1
            repository.commit()
        except Exception as error:
            repository.rollback()
            failed += 1
            logger.error(
                "Could not resolve %s (%s)",
                signal.canonical_url,
                type(error).__name__,
            )

    return DedupeResult(
        examined=len(pending),
        primaries=primaries,
        duplicates=duplicates,
        failed=failed,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_dedupe.py -v`
Expected: PASS, 9 tests

- [ ] **Step 6: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/dedupe.py packages/backend/src/episignal_backend/ingestion/protocol.py packages/backend/tests/test_dedupe.py
git commit -m "feat: resolve syndicated copies to one primary signal"
```

---

## Task 11: Storage for the deduplication pass

**Files:**
- Modify: `packages/backend/src/episignal_backend/ingestion/repository.py`
- Test: `packages/backend/tests/test_dedupe_repository.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_dedupe_repository.py`:

```python
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from episignal_backend.db.types import ProcessingStatus
from episignal_backend.ingestion.documents import ComparableSignal
from episignal_backend.ingestion.protocol import DedupeRepository
from episignal_backend.ingestion.repository import SqlAlchemyDedupeRepository
from episignal_backend.models import Signal

FIRST = datetime(2026, 8, 25, 19, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> Any:
        return self._value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = results or []
        self.executed: list[Any] = []

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return self._results.pop(0) if self._results else FakeResult(None)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def row(**overrides: Any) -> Signal:
    signal = Signal(
        source_id=uuid4(),
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        title="Measles deaths confirmed",
        raw_text="Two people died.",
        retrieved_at=FIRST,
        first_seen_at=FIRST,
        content_hash="a" * 64,
    )
    signal.id = uuid4()
    for name, value in overrides.items():
        setattr(signal, name, value)
    return signal


def test_pending_returns_comparable_signals() -> None:
    stored = row()
    session = FakeSession([FakeResult([stored])])
    repository = SqlAlchemyDedupeRepository(session)

    pending = repository.pending(limit=10)

    assert len(pending) == 1
    assert isinstance(pending[0], ComparableSignal)
    assert pending[0].id == stored.id
    assert pending[0].content_hash == "a" * 64


def test_marking_a_duplicate_issues_one_update() -> None:
    session = FakeSession()
    repository = SqlAlchemyDedupeRepository(session)

    repository.mark_duplicate(uuid4(), uuid4())

    assert len(session.executed) == 1


def test_marking_normalized_issues_one_update() -> None:
    session = FakeSession()
    repository = SqlAlchemyDedupeRepository(session)

    repository.mark_normalized(uuid4())

    assert len(session.executed) == 1


def test_primary_of_returns_the_id_itself_when_it_is_not_a_duplicate() -> None:
    identifier = uuid4()
    session = FakeSession([FakeResult(None)])
    repository = SqlAlchemyDedupeRepository(session)

    assert repository.primary_of(identifier) == identifier


def test_primary_of_follows_a_chain_to_its_end() -> None:
    root = uuid4()
    middle = uuid4()
    leaf = uuid4()
    session = FakeSession([FakeResult(middle), FakeResult(root), FakeResult(None)])
    repository = SqlAlchemyDedupeRepository(session)

    assert repository.primary_of(leaf) == root


def test_the_repository_satisfies_the_dedupe_protocol() -> None:
    assert isinstance(SqlAlchemyDedupeRepository(FakeSession()), DedupeRepository)


def test_pending_selects_only_fetched_rows_with_a_body() -> None:
    session = FakeSession([FakeResult([])])
    repository = SqlAlchemyDedupeRepository(session)

    repository.pending(limit=5)

    rendered = str(session.executed[0])
    assert "processing_status" in rendered
    assert "raw_text IS NOT NULL" in rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_dedupe_repository.py -v`
Expected: FAIL with `ImportError: cannot import name 'SqlAlchemyDedupeRepository'`

- [ ] **Step 3: Write minimal implementation**

In `packages/backend/src/episignal_backend/ingestion/repository.py`, extend the SQLAlchemy imports:

```python
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
```

Add the converter next to `build_discovered_signal`:

```python
def build_comparable(signal: Signal) -> ComparableSignal:
    return ComparableSignal(
        id=signal.id,
        canonical_url=signal.canonical_url or signal.url,
        title=signal.title,
        # Callers only ever select rows where this is not null; the assertion
        # documents that rather than silently substituting an empty string.
        raw_text=signal.raw_text or "",
        content_hash=signal.content_hash,
        first_seen_at=signal.first_seen_at,
        published_at=signal.published_at,
        duplicate_of_signal_id=signal.duplicate_of_signal_id,
    )
```

Append the new repository to the end of the file:

```python
class SqlAlchemyDedupeRepository:
    """Storage for Stage 0's second gate.

    Deliberately unable to discover or fetch: this pass reads stored signals and
    writes their status, and nothing else.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def pending(self, *, limit: int) -> Sequence[ComparableSignal]:
        rows = self._session.execute(
            select(Signal)
            .where(
                Signal.processing_status == ProcessingStatus.FETCHED,
                # Stubs stay in the retry path: a document with no body cannot
                # be compared on one, and comparing on the title alone is the
                # merge this design refuses.
                Signal.raw_text.is_not(None),
            )
            .order_by(Signal.first_seen_at)
            .limit(limit)
        ).scalars()
        return tuple(build_comparable(row) for row in rows)

    def candidates(
        self, signal: ComparableSignal, *, window_hours: int
    ) -> Sequence[ComparableSignal]:
        span = timedelta(hours=window_hours)
        rows = self._session.execute(
            select(Signal)
            .where(
                Signal.id != signal.id,
                Signal.raw_text.is_not(None),
                or_(
                    # An identical hash is compared regardless of age, so a late
                    # republication of unchanged text is still caught.
                    Signal.content_hash == signal.content_hash,
                    and_(
                        Signal.first_seen_at >= signal.first_seen_at - span,
                        Signal.first_seen_at <= signal.first_seen_at + span,
                    ),
                ),
            )
            .order_by(Signal.first_seen_at)
        ).scalars()
        return tuple(build_comparable(row) for row in rows)

    def primary_of(self, signal_id: UUID) -> UUID:
        seen: set[UUID] = set()
        current = signal_id
        while current not in seen:
            seen.add(current)
            parent = self._session.execute(
                select(Signal.duplicate_of_signal_id).where(Signal.id == current)
            ).scalar_one_or_none()
            if parent is None:
                return current
            current = parent
        # Unreachable while pointers are flattened on assignment. Returning the
        # last id rather than looping forever keeps a corrupted row survivable.
        return current

    def mark_duplicate(self, signal_id: UUID, primary_id: UUID) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(
                processing_status=ProcessingStatus.DUPLICATE,
                duplicate_of_signal_id=primary_id,
            )
        )

    def mark_normalized(self, signal_id: UUID) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(processing_status=ProcessingStatus.NORMALIZED)
        )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
```

Add `ProcessingStatus` to the `db.types` import at the top of the file:

```python
from episignal_backend.db.types import (
    CredibilityTier,
    DiscoveryMethod,
    ProcessingStatus,
    SourceType,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_dedupe_repository.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/repository.py packages/backend/tests/test_dedupe_repository.py
git commit -m "feat: read and mark signals for the deduplication pass"
```

---

## Task 12: Configuration and the command

**Files:**
- Modify: `packages/backend/src/episignal_backend/config.py`
- Create: `packages/backend/src/episignal_backend/dedupe_runner.py`
- Modify: `package.json`
- Test: `packages/backend/tests/test_config.py`
- Test: `packages/backend/tests/test_dedupe_runner.py`

- [ ] **Step 1: Write the failing config test**

Append to `packages/backend/tests/test_config.py`. The file constructs `Settings` directly with an explicit URL and `_env_file=None`, so these follow that:

```python
DATABASE_URL = "postgresql://user:secret@host/db"


def test_stage0_defaults_are_strict() -> None:
    settings = Settings(database_url=DATABASE_URL, _env_file=None)  # type: ignore[call-arg, arg-type]

    assert settings.stage0_title_similarity == 0.90
    assert settings.stage0_body_similarity == 0.80
    assert settings.stage0_shingle_size == 5
    assert settings.stage0_candidate_window_hours == 72
    assert settings.stage0_batch_size == 200


def test_a_similarity_threshold_above_one_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[call-arg, arg-type]
            database_url=DATABASE_URL,
            stage0_title_similarity=1.5,
            _env_file=None,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_config.py -k stage0 -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'stage0_title_similarity'`

- [ ] **Step 3: Add the settings**

In `packages/backend/src/episignal_backend/config.py`, add after `gdelt_user_agent`:

```python
    # The two thresholds are configuration because they are the numbers most
    # likely to need tuning against real traffic, and because the architecture
    # requires matching thresholds to stay configurable rather than compiled in.
    stage0_title_similarity: float = Field(default=0.90, ge=0.0, le=1.0)
    stage0_body_similarity: float = Field(default=0.80, ge=0.0, le=1.0)
    stage0_shingle_size: int = Field(default=5, ge=1, le=20)
    stage0_candidate_window_hours: int = Field(default=72, ge=1, le=720)
    stage0_batch_size: int = Field(default=200, ge=1, le=5000)
```

- [ ] **Step 4: Write the failing runner test**

Create `packages/backend/tests/test_dedupe_runner.py`:

```python
from typing import Any

import pytest

from episignal_backend import dedupe_runner
from episignal_backend.ingestion.dedupe import DedupeResult


def test_arguments_default_to_none() -> None:
    arguments = dedupe_runner.parse_arguments([])

    assert arguments.batch_size is None
    assert arguments.window_hours is None


def test_arguments_are_parsed_past_the_pnpm_separator() -> None:
    arguments = dedupe_runner.parse_arguments(["--", "--batch-size", "10"])

    assert arguments.batch_size == 10


def test_counts_are_printed_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(arguments: Any) -> DedupeResult:
        return DedupeResult(examined=4, primaries=1, duplicates=3, failed=0)

    monkeypatch.setattr(dedupe_runner, "_run", fake_run)

    assert dedupe_runner.main([]) == 0
    assert "examined=4 primaries=1 duplicates=3 failed=0" in capsys.readouterr().out


def test_a_failure_is_reported_without_detail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(arguments: Any) -> DedupeResult:
        raise RuntimeError("postgresql://user:secret@host/db is unreachable")

    monkeypatch.setattr(dedupe_runner, "_run", fake_run)

    assert dedupe_runner.main([]) == 1
    captured = capsys.readouterr()
    assert "secret" not in captured.err
    assert "Deduplication failed" in captured.err
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_dedupe_runner.py -v`
Expected: FAIL with `ImportError: cannot import name 'dedupe_runner'`

- [ ] **Step 6: Write the runner**

Create `packages/backend/src/episignal_backend/dedupe_runner.py`:

```python
"""Entry point for `pnpm dedupe:signals`.

Counts only. The connection string and stored bodies never reach stdout, the
same posture as `discover_runner.py`.

Re-running is safe: only signals still awaiting a decision are selected, so a
second run in the same minute does nothing.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.ingestion.dedupe import DedupeResult, DedupeThresholds, run_dedupe
from episignal_backend.ingestion.repository import SqlAlchemyDedupeRepository


@dataclass(frozen=True)
class Arguments:
    batch_size: int | None
    window_hours: int | None


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="dedupe", description="Resolve syndicated copies to one primary signal."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Signals to examine this run. Defaults to EPISIGNAL_STAGE0_BATCH_SIZE.",
    )
    parser.add_argument(
        "--window-hours",
        type=int,
        default=None,
        help="Comparison window. Defaults to EPISIGNAL_STAGE0_CANDIDATE_WINDOW_HOURS.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(batch_size=parsed.batch_size, window_hours=parsed.window_hours)


def _run(arguments: Arguments) -> DedupeResult:
    settings = get_settings()
    with session_scope() as session:
        return run_dedupe(
            SqlAlchemyDedupeRepository(session),
            thresholds=DedupeThresholds(
                title=settings.stage0_title_similarity,
                body=settings.stage0_body_similarity,
                shingle_size=settings.stage0_shingle_size,
            ),
            window_hours=arguments.window_hours or settings.stage0_candidate_window_hours,
            batch_size=arguments.batch_size or settings.stage0_batch_size,
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        result = _run(arguments)
    except Exception:
        print("Deduplication failed before completing. Check the database.", file=sys.stderr)
        return 1

    print(
        f"examined={result.examined} primaries={result.primaries} "
        f"duplicates={result.duplicates} failed={result.failed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Register the command**

In `package.json`, add after the `discover:gdelt` line:

```json
    "dedupe:signals": "uv run --package episignal-backend python -m episignal_backend.dedupe_runner",
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_dedupe_runner.py packages/backend/tests/test_config.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add packages/backend/src/episignal_backend/config.py packages/backend/src/episignal_backend/dedupe_runner.py package.json packages/backend/tests/test_dedupe_runner.py packages/backend/tests/test_config.py
git commit -m "feat: add the deduplication command and its configuration"
```

---

## Task 13: Live verification and the quality gates

**Files:**
- Modify: `README.md` (command list only, if it lists the others)

- [ ] **Step 1: Run every gate**

```bash
uv run pytest
```

Expected: all tests pass, zero failures. The suite stood at 296 before this plan.

```bash
uv run ruff check .
```

Expected: `All checks passed!`

```bash
uv run ruff format --check .
```

Expected: `N files already formatted`

```bash
uv run mypy apps/api/src packages/backend/src
```

Expected: `Success: no issues found`

Fix anything that fails before continuing. Do not proceed with a failing gate.

- [ ] **Step 2: Verify gate one against the live pipeline**

```bash
pnpm db:migrate
pnpm db:seed
pnpm discover:gdelt -- --window-minutes 1440 --max-articles 25
```

Expected: the printed line now includes `rules_invalid=0` and a `rejected=` count. `rules_invalid` must be `0`; any other value means a seeded pattern does not compile, and Task 7's test should have caught it.

- [ ] **Step 3: Verify gate two against stored signals**

```bash
pnpm dedupe:signals
```

Expected: `examined=N primaries=... duplicates=... failed=0`.

Run it a second time:

```bash
pnpm dedupe:signals
```

Expected: `examined=0 primaries=0 duplicates=0 failed=0`. A non-zero `examined` on the second run means signals are not being marked, and the pass is not idempotent.

- [ ] **Step 4: Confirm the invariants in the database**

```bash
uv run --package episignal-api python -c "
from sqlalchemy import select, func
from episignal_backend.db.session import session_scope
from episignal_backend.models import Signal, RejectedSighting
with session_scope() as session:
    print('rejections', session.execute(select(func.count()).select_from(RejectedSighting)).scalar_one())
    print('unattributed', session.execute(select(func.count()).select_from(RejectedSighting).where(RejectedSighting.filter_rule_id.is_(None))).scalar_one())
    primary = select(Signal.id).where(Signal.duplicate_of_signal_id.is_not(None)).subquery()
    print('chained', session.execute(select(func.count()).select_from(Signal).where(Signal.duplicate_of_signal_id.in_(select(primary.c.id)))).scalar_one())
"
```

Expected: `unattributed 0` and `chained 0`. Every rejection names its rule, and no pointer leads to another pointer.

- [ ] **Step 5: Document the command**

In `README.md`, add one line to the command list immediately after `pnpm discover:gdelt`:

```text
pnpm dedupe:signals    # resolve syndicated copies to one primary signal
```

In the same list, the `pnpm db:seed` line currently reads `seed canonical diseases, sources, and GDELT query rules`. Extend it to `seed canonical diseases, sources, GDELT query rules, and Stage 0 filter rules`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: verify Stage 0 filtering and deduplication end to end"
```

---

## Acceptance criteria

Check each against the spec before calling this done:

- [ ] An article matching a title exclusion or a blocklisted domain costs no page fetch and no signal row.
- [ ] Every rejection is recorded with the rule that caused it and is queryable.
- [ ] A retuned rule admits a previously rejected URL on its next sighting without manual cleanup.
- [ ] The two syndicated copies in the fixture resolve to one primary and one duplicate, each keeping its own publisher and original URL.
- [ ] Two independent articles sharing a headline but not a body remain two signals.
- [ ] The primary is the earliest sighting, and no `duplicate_of_signal_id` points at a row that is itself a duplicate.
- [ ] A stub is never selected, never compared, and never marked.
- [ ] Re-running the dedup pass changes nothing.
- [ ] No AI model is called and no embedding is computed anywhere in this slice.
- [ ] WHO and ECDC ingestion is unchanged and still passes its tests.
- [ ] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy apps/api/src packages/backend/src` all pass.

## Known follow-on work, deliberately not in this plan

- **Classification and extraction** are sub-project C. They read `processing_status='normalized'`, the state this plan starts writing.
- **Story clustering across different articles** is sub-project D. This plan groups the same article republished, and nothing more.
- **An admin view of rejected sightings** belongs to sub-project E. The table and its rule attribution exist so that view has something to show.

## Primary references

- `docs/superpowers/specs/2026-08-27-gdelt-stage0-filtering-design.md`
- `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md`
- `docs/superpowers/plans/2026-08-27-gdelt-discovery.md` — the plan this one extends.
