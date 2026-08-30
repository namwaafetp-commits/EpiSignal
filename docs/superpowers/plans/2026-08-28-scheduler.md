# Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the whole pipeline once a day from one command, record what each run did, and never let a missed day silently lose a day of news.

**Architecture:** A new `episignal_backend/schedule/` package with the same seam `events/` has — pure modules for ordering, failure policy, and window arithmetic; one adapter that opens sessions and calls the existing runner paths; one module that imports SQLAlchemy. A new `pipeline_runs` table records each run. Windows Task Scheduler is the trigger; no daemon exists.

**Tech Stack:** Python 3.12, SQLAlchemy 2 with `Mapped`/`mapped_column`, Alembic, pydantic-settings, pytest, PostgreSQL with PostGIS.

**Spec:** `docs/superpowers/specs/2026-08-28-scheduler-design.md`

---

## Before you start

Read `HANDOFF.md`, then this plan, then the spec. Three project rules that are
not negotiable and that this plan assumes throughout:

1. **No test touches a database, a socket, or a model.** There is no
   `conftest.py` and no test fixture database in this repository. Repository
   tests use a hand-written `FakeSession` — copy the one at the top of
   `packages/backend/tests/test_event_repository.py`. Only task 18 touches the
   live database.
2. **Tick your task in `STATUS.md` in the same commit as the work.**
3. **Pure modules import no SQLAlchemy, no GeoAlchemy2, and no httpx.** Task 16
   adds the test that enforces it. Do not wait for task 16 to obey it.

Run the full suite with `uv run pytest`. Run one test with
`uv run pytest packages/backend/tests/test_schedule_run.py -v`.

---

### Task 1: Contracts across the seams

**Files:**
- Create: `packages/backend/src/episignal_backend/schedule/__init__.py`
- Create: `packages/backend/src/episignal_backend/schedule/documents.py`
- Test: `packages/backend/tests/test_schedule_documents.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime

from episignal_backend.schedule.documents import (
    ChainOutcome,
    DiscoveryWindow,
    StageName,
    StageOutcome,
)


def test_stage_names_are_their_lowercase_values() -> None:
    assert StageName.INGEST_WHO == "ingest_who"
    assert StageName.MATCH == "match"


def test_a_window_reports_its_span_in_whole_minutes() -> None:
    window = DiscoveryWindow(
        start=datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
        end=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )

    assert window.minutes == 1440


def test_a_window_shorter_than_a_minute_still_asks_for_one() -> None:
    moment = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

    assert DiscoveryWindow(start=moment, end=moment).minutes == 1


def test_a_chain_with_no_failures_is_ok() -> None:
    outcome = ChainOutcome(
        outcomes=(
            StageOutcome(stage=StageName.DEDUPE, ok=True, counts={"examined": 3}),
        )
    )

    assert outcome.ok is True
    assert outcome.failed_stages == ()


def test_a_chain_names_every_stage_that_failed() -> None:
    outcome = ChainOutcome(
        outcomes=(
            StageOutcome(stage=StageName.EXTRACT, ok=False, error="TimeoutError"),
            StageOutcome(stage=StageName.GEOCODE, ok=True, counts={"located": 2}),
            StageOutcome(stage=StageName.MATCH, ok=False, error="OperationalError"),
        )
    )

    assert outcome.ok is False
    assert outcome.failed_stages == (StageName.EXTRACT, StageName.MATCH)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/backend/tests/test_schedule_documents.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'episignal_backend.schedule'`

- [ ] **Step 3: Write the implementation**

`schedule/__init__.py` is empty. `schedule/documents.py`:

```python
"""Contracts across the scheduler's seams.

Pure data. This module imports neither SQLAlchemy nor httpx, so the ordering,
the failure policy, and the window arithmetic can be tested without a database,
a socket, or a model call.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class StageName(StrEnum):
    """One step of the pipeline. Never a rung of the model ladder: that is a tier."""

    INGEST_WHO = "ingest_who"
    INGEST_ECDC = "ingest_ecdc"
    DISCOVER = "discover"
    DEDUPE = "dedupe"
    EXTRACT = "extract"
    GEOCODE = "geocode"
    MATCH = "match"


@dataclass(frozen=True)
class DiscoveryWindow:
    """The span of publication time a discovery pass asks GDELT for."""

    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        # run_discovery takes minutes, not instants. A window rounding to zero
        # would ask for nothing at all, so the floor is one minute.
        return max(1, int((self.end - self.start).total_seconds() // 60))


@dataclass(frozen=True)
class StageOutcome:
    """What one stage did, or the type of the exception that stopped it."""

    stage: StageName
    ok: bool
    counts: Mapping[str, int] = field(default_factory=dict)
    # The exception's type name only. Never its payload: an exception raised
    # near the session can carry the connection string.
    error: str | None = None


@dataclass(frozen=True)
class ChainOutcome:
    outcomes: tuple[StageOutcome, ...]

    @property
    def failed_stages(self) -> tuple[StageName, ...]:
        return tuple(outcome.stage for outcome in self.outcomes if not outcome.ok)

    @property
    def ok(self) -> bool:
        return not self.failed_stages
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/backend/tests/test_schedule_documents.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/schedule packages/backend/tests/test_schedule_documents.py STATUS.md
git commit -m "feat: declare the scheduler's seam contracts"
```

---

### Task 2: The daily chain

**Files:**
- Create: `packages/backend/src/episignal_backend/schedule/chains.py`
- Test: `packages/backend/tests/test_schedule_chains.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from episignal_backend.schedule.chains import CHAINS, DAILY_CHAIN, chain_for
from episignal_backend.schedule.documents import StageName


def test_official_sources_are_ingested_before_media_is_matched() -> None:
    assert DAILY_CHAIN == (
        StageName.INGEST_WHO,
        StageName.INGEST_ECDC,
        StageName.DISCOVER,
        StageName.DEDUPE,
        StageName.EXTRACT,
        StageName.GEOCODE,
        StageName.MATCH,
    )


def test_every_stage_appears_exactly_once() -> None:
    assert len(set(DAILY_CHAIN)) == len(DAILY_CHAIN)
    assert set(DAILY_CHAIN) == set(StageName)


def test_a_chain_is_looked_up_by_name() -> None:
    assert chain_for("daily") == DAILY_CHAIN
    assert set(CHAINS) == {"daily"}


def test_an_unknown_chain_is_refused_by_name() -> None:
    with pytest.raises(KeyError):
        chain_for("hourly")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/backend/tests/test_schedule_chains.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'episignal_backend.schedule.chains'`

- [ ] **Step 3: Write the implementation**

```python
"""The order the stages run in.

One chain exists. The order is a decision, not an accident: WHO and ECDC are
ingested first so an official document that corroborates a story is in the
database before that story's media coverage is matched to an event.
"""

from episignal_backend.schedule.documents import StageName

DAILY_CHAIN: tuple[StageName, ...] = (
    StageName.INGEST_WHO,
    StageName.INGEST_ECDC,
    StageName.DISCOVER,
    StageName.DEDUPE,
    StageName.EXTRACT,
    StageName.GEOCODE,
    StageName.MATCH,
)

CHAINS: dict[str, tuple[StageName, ...]] = {"daily": DAILY_CHAIN}


def chain_for(name: str) -> tuple[StageName, ...]:
    return CHAINS[name]
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/backend/tests/test_schedule_chains.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/schedule/chains.py packages/backend/tests/test_schedule_chains.py STATUS.md
git commit -m "feat: define the daily chain and its order"
```

---

### Task 3: The catch-up window

This is the task that makes a missed day recoverable. Read the spec's "A missed
day is repaired, not lost" before writing it.

**Files:**
- Create: `packages/backend/src/episignal_backend/schedule/window.py`
- Test: `packages/backend/tests/test_schedule_window.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime, timedelta

from episignal_backend.schedule.window import catch_up_window

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def test_the_first_run_ever_falls_back_to_the_configured_window() -> None:
    window = catch_up_window(
        now=NOW, last_window_end=None, default_minutes=1500, max_minutes=10080
    )

    assert window.end == NOW
    assert window.start == NOW - timedelta(minutes=1500)


def test_a_later_run_starts_where_the_last_one_stopped() -> None:
    previous_end = NOW - timedelta(hours=26)

    window = catch_up_window(
        now=NOW, last_window_end=previous_end, default_minutes=1500, max_minutes=10080
    )

    assert window.start == previous_end
    assert window.end == NOW
    assert window.minutes == 26 * 60


def test_a_long_gap_is_clamped_rather_than_asked_for_in_full() -> None:
    window = catch_up_window(
        now=NOW,
        last_window_end=NOW - timedelta(days=90),
        default_minutes=1500,
        max_minutes=10080,
    )

    assert window.start == NOW - timedelta(minutes=10080)
    assert window.minutes == 10080


def test_a_last_window_end_in_the_future_does_not_invert_the_window() -> None:
    # A clock change, or a row written by a machine whose clock was ahead.
    window = catch_up_window(
        now=NOW,
        last_window_end=NOW + timedelta(hours=3),
        default_minutes=1500,
        max_minutes=10080,
    )

    assert window.start == NOW
    assert window.end == NOW
    assert window.minutes == 1
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/backend/tests/test_schedule_window.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'episignal_backend.schedule.window'`

- [ ] **Step 3: Write the implementation**

```python
"""How far back a discovery pass looks.

Discovery's window is anchored to the moment of the run, and nothing else in the
system records how far back it has already looked. On a daily cadence run from a
laptop that sleeps, that would make every hour the machine was off an hour no
run ever asks for again. So the window starts where the last successful run
stopped.
"""

from datetime import datetime, timedelta

from episignal_backend.schedule.documents import DiscoveryWindow


def catch_up_window(
    *,
    now: datetime,
    last_window_end: datetime | None,
    default_minutes: int,
    max_minutes: int,
) -> DiscoveryWindow:
    earliest = now - timedelta(minutes=max_minutes)

    if last_window_end is None:
        start = now - timedelta(minutes=default_minutes)
    else:
        start = last_window_end

    # The clamp loses news. It loses it loudly: the run records the window it
    # actually asked for, so a truncated catch-up is a row rather than a hole.
    start = max(start, earliest)
    # A clock that moved backwards must not produce an inverted window.
    start = min(start, now)

    return DiscoveryWindow(start=start, end=now)
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/backend/tests/test_schedule_window.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/schedule/window.py packages/backend/tests/test_schedule_window.py STATUS.md
git commit -m "feat: compute the discovery window from the last successful run"
```

---

### Task 4: The storage boundary

**Files:**
- Create: `packages/backend/src/episignal_backend/schedule/protocol.py`
- Test: `packages/backend/tests/test_schedule_protocol.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from uuid import UUID, uuid4

from episignal_backend.db.types import PipelineChain, PipelineRunStatus, PipelineTrigger
from episignal_backend.schedule.documents import DiscoveryWindow, StageName
from episignal_backend.schedule.protocol import PipelineRunRepository


class StubRepository:
    def try_lock(self) -> bool:
        return True

    def unlock(self) -> None:
        return None

    def last_window_end(self, chain: PipelineChain) -> datetime | None:
        return None

    def start_run(
        self,
        *,
        chain: PipelineChain,
        trigger: PipelineTrigger,
        started_at: datetime,
        window: DiscoveryWindow | None,
    ) -> UUID:
        return uuid4()

    def finish_run(
        self,
        run_id: UUID,
        *,
        status: PipelineRunStatus,
        finished_at: datetime,
        stage_counts: dict[str, dict[str, int]],
        backlog: dict[str, int],
        failed_stages: list[StageName],
    ) -> None:
        return None

    def backlog_depth(self) -> dict[str, int]:
        return {}


def test_a_conforming_repository_satisfies_the_protocol() -> None:
    assert isinstance(StubRepository(), PipelineRunRepository)


def test_a_repository_missing_the_lock_does_not_satisfy_the_protocol() -> None:
    class NoLock:
        def unlock(self) -> None:
            return None

    assert not isinstance(NoLock(), PipelineRunRepository)


def test_the_protocol_imports_no_database_driver() -> None:
    import episignal_backend.schedule.protocol as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "sqlalchemy" not in source.lower()


def test_started_at_is_recorded_before_any_stage_runs() -> None:
    # The row exists before the work, so a killed run leaves the evidence that
    # it was killed rather than leaving no trace at all.
    repository = StubRepository()
    run_id = repository.start_run(
        chain=PipelineChain.DAILY,
        trigger=PipelineTrigger.MANUAL,
        started_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        window=None,
    )

    assert isinstance(run_id, UUID)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/backend/tests/test_schedule_protocol.py -v`
Expected: FAIL, `ImportError: cannot import name 'PipelineChain' from 'episignal_backend.db.types'`

Task 5 adds those enums. Write this test now and leave it red; it goes green in
task 5. If you would rather not leave a red test across a commit, do task 5
first and come back — the order of 4 and 5 does not matter.

- [ ] **Step 3: Write the implementation**

```python
"""The storage boundary for scheduled pipeline runs.

`PipelineRunRepository` declares the contract between the chain and storage. The
repository owns the connection, the advisory lock, and the transaction: nothing
above it knows what a session is.

This module imports neither SQLAlchemy nor httpx.
"""

from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from episignal_backend.db.types import PipelineChain, PipelineRunStatus, PipelineTrigger
from episignal_backend.schedule.documents import DiscoveryWindow, StageName


@runtime_checkable
class PipelineRunRepository(Protocol):
    """The storage contract for recording a run and serialising runs against each other."""

    def try_lock(self) -> bool:
        """Take the session-level advisory lock. False means a run is already in progress."""
        ...

    def unlock(self) -> None:
        """Release the advisory lock. Safe to call when the lock was never taken."""
        ...

    def last_window_end(self, chain: PipelineChain) -> datetime | None:
        """The window_end of the most recent run of this chain that discovered successfully."""
        ...

    def start_run(
        self,
        *,
        chain: PipelineChain,
        trigger: PipelineTrigger,
        started_at: datetime,
        window: DiscoveryWindow | None,
    ) -> UUID:
        """Insert a row at status running, before the first stage executes."""
        ...

    def finish_run(
        self,
        run_id: UUID,
        *,
        status: PipelineRunStatus,
        finished_at: datetime,
        stage_counts: dict[str, dict[str, int]],
        backlog: dict[str, int],
        failed_stages: list[StageName],
    ) -> None:
        """Close the row out with what every stage did."""
        ...

    def backlog_depth(self) -> dict[str, int]:
        """Count signals by processing_status, so a growing backlog is a recorded fact."""
        ...
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/backend/tests/test_schedule_protocol.py -v`
Expected: PASS after task 5 lands, 4 tests

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/schedule/protocol.py packages/backend/tests/test_schedule_protocol.py STATUS.md
git commit -m "feat: declare the pipeline run storage boundary"
```

---

### Task 5: The persisted vocabularies

**Files:**
- Modify: `packages/backend/src/episignal_backend/db/types.py`
- Test: `packages/backend/tests/test_schedule_types.py`

- [ ] **Step 1: Write the failing test**

```python
from episignal_backend.db.types import (
    PipelineChain,
    PipelineRunStatus,
    PipelineTrigger,
    vocabulary,
)


def test_the_vocabularies_store_their_lowercase_values() -> None:
    assert PipelineChain.DAILY == "daily"
    assert PipelineTrigger.SCHEDULED == "scheduled"
    assert PipelineRunStatus.RUNNING == "running"


def test_a_run_is_running_succeeded_or_failed() -> None:
    assert {status.value for status in PipelineRunStatus} == {
        "running",
        "succeeded",
        "failed",
    }


def test_a_scheduled_run_is_distinguishable_from_a_manual_one() -> None:
    # The MVP question is whether Task Scheduler actually fired, which a run
    # invoked by hand would otherwise disguise.
    assert {trigger.value for trigger in PipelineTrigger} == {"scheduled", "manual"}


def test_the_vocabularies_are_stored_as_values_not_member_names() -> None:
    column_type = vocabulary(PipelineRunStatus, "pipeline_run_status")

    assert sorted(column_type.enums) == ["failed", "running", "succeeded"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/backend/tests/test_schedule_types.py -v`
Expected: FAIL, `ImportError: cannot import name 'PipelineChain'`

- [ ] **Step 3: Write the implementation**

Append to `db/types.py`, above the `vocabulary` helper:

```python
class PipelineChain(StrEnum):
    DAILY = "daily"


class PipelineTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class PipelineRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    # Some stage raised. The chain still ran every later stage.
    FAILED = "failed"
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/backend/tests/test_schedule_types.py packages/backend/tests/test_schedule_protocol.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/db/types.py packages/backend/tests/test_schedule_types.py STATUS.md
git commit -m "feat: add the pipeline run vocabularies"
```

---

### Task 6: The chain runner and its failure policy

This is the heart of the item, and it is pure. No session, no settings, no
network.

**Files:**
- Create: `packages/backend/src/episignal_backend/schedule/run.py`
- Test: `packages/backend/tests/test_schedule_run.py`

- [ ] **Step 1: Write the failing test**

```python
from collections.abc import Mapping

from episignal_backend.schedule.documents import StageName
from episignal_backend.schedule.run import run_chain


def _record(calls: list[StageName], stage: StageName, counts: dict[str, int]):
    def runner() -> Mapping[str, int]:
        calls.append(stage)
        return counts

    return runner


def _raises(calls: list[StageName], stage: StageName, error: Exception):
    def runner() -> Mapping[str, int]:
        calls.append(stage)
        raise error

    return runner


def test_stages_run_in_the_order_the_chain_gives() -> None:
    calls: list[StageName] = []
    chain = (StageName.DEDUPE, StageName.EXTRACT, StageName.GEOCODE)
    runners = {stage: _record(calls, stage, {"examined": 1}) for stage in chain}

    run_chain(chain, runners)

    assert calls == [StageName.DEDUPE, StageName.EXTRACT, StageName.GEOCODE]


def test_a_failing_stage_does_not_stop_the_ones_after_it() -> None:
    calls: list[StageName] = []
    chain = (StageName.EXTRACT, StageName.GEOCODE, StageName.MATCH)
    runners = {
        StageName.EXTRACT: _raises(calls, StageName.EXTRACT, TimeoutError("upstream")),
        StageName.GEOCODE: _record(calls, StageName.GEOCODE, {"located": 4}),
        StageName.MATCH: _record(calls, StageName.MATCH, {"created": 1}),
    }

    outcome = run_chain(chain, runners)

    assert calls == [StageName.EXTRACT, StageName.GEOCODE, StageName.MATCH]
    assert outcome.ok is False
    assert outcome.failed_stages == (StageName.EXTRACT,)


def test_a_failure_records_the_exception_type_and_never_its_message() -> None:
    chain = (StageName.MATCH,)
    secret = "postgresql://user:hunter2@host/db is unreachable"
    runners = {StageName.MATCH: _raises([], StageName.MATCH, OSError(secret))}

    outcome = run_chain(chain, runners)

    assert outcome.outcomes[0].error == "OSError"
    assert "hunter2" not in str(outcome.outcomes[0])


def test_counts_are_kept_per_stage() -> None:
    chain = (StageName.GEOCODE,)
    runners = {StageName.GEOCODE: _record([], StageName.GEOCODE, {"located": 7})}

    outcome = run_chain(chain, runners)

    assert outcome.outcomes[0].counts == {"located": 7}
    assert outcome.ok is True


def test_a_stage_with_no_runner_is_a_failure_not_a_crash() -> None:
    outcome = run_chain((StageName.MATCH,), {})

    assert outcome.ok is False
    assert outcome.outcomes[0].error == "KeyError"
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/backend/tests/test_schedule_run.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'episignal_backend.schedule.run'`

- [ ] **Step 3: Write the implementation**

```python
"""Running one chain, in order, with the failure policy the design settled on.

Every stage selects its own backlog by processing_status, so a failed extraction
does not invalidate signals extracted yesterday and waiting to be geocoded. The
chain therefore runs every stage and reports which ones failed, rather than
aborting on the first.

Pure. The caller supplies the stage callables, which is what makes the ordering
and the failure policy testable without a database.
"""

from collections.abc import Callable, Mapping, Sequence

from episignal_backend.schedule.documents import ChainOutcome, StageName, StageOutcome

StageRunner = Callable[[], Mapping[str, int]]


def run_chain(
    chain: Sequence[StageName],
    runners: Mapping[StageName, StageRunner],
) -> ChainOutcome:
    outcomes: list[StageOutcome] = []

    for stage in chain:
        try:
            counts = runners[stage]()
        except Exception as error:
            # The type name only. An exception raised near the session can carry
            # the connection string, and one raised near a prompt can carry the
            # article.
            outcomes.append(
                StageOutcome(stage=stage, ok=False, error=type(error).__name__)
            )
            continue
        outcomes.append(StageOutcome(stage=stage, ok=True, counts=dict(counts)))

    return ChainOutcome(outcomes=tuple(outcomes))
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/backend/tests/test_schedule_run.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/schedule/run.py packages/backend/tests/test_schedule_run.py STATUS.md
git commit -m "feat: run a chain in order and continue past a failing stage"
```

---

### Task 7: The PipelineRun model

**Files:**
- Create: `packages/backend/src/episignal_backend/models/pipeline.py`
- Modify: `packages/backend/src/episignal_backend/models/__init__.py`
- Modify: `packages/backend/tests/test_models.py:5-21`
- Test: `packages/backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Add `"pipeline_runs"` to the `EXPECTED_TABLES` set at
`packages/backend/tests/test_models.py:5`, then append:

```python
def test_a_pipeline_run_records_the_window_it_asked_for() -> None:
    table = Base.metadata.tables["pipeline_runs"]

    assert {"window_start", "window_end"} <= set(table.columns)
    assert table.columns["window_start"].nullable is True


def test_a_pipeline_run_starts_before_it_finishes() -> None:
    table = Base.metadata.tables["pipeline_runs"]

    assert table.columns["started_at"].nullable is False
    # Null until the run closes out, which is how a killed run is recognised.
    assert table.columns["finished_at"].nullable is True


def test_stage_counts_and_backlog_default_to_empty_rather_than_null() -> None:
    table = Base.metadata.tables["pipeline_runs"]

    for name in ("stage_counts", "backlog", "failed_stages"):
        assert table.columns[name].nullable is False
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/backend/tests/test_models.py -v`
Expected: FAIL, `KeyError: 'pipeline_runs'`

- [ ] **Step 3: Write the implementation**

`models/pipeline.py`:

```python
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin, TimestampMixin
from episignal_backend.db.types import (
    PipelineChain,
    PipelineRunStatus,
    PipelineTrigger,
    vocabulary,
)


class PipelineRun(IdentityMixin, TimestampMixin, Base):
    """One execution of one chain.

    The row is inserted before the first stage runs, so a run killed mid-flight
    leaves a `running` row with a null `finished_at`. That is the evidence it
    was killed, and nothing cleans it up.
    """

    __tablename__ = "pipeline_runs"
    __table_args__ = (
        # The only query the code makes: the most recent run of a chain.
        Index("ix_pipeline_runs_chain_started_at", "chain", text("started_at DESC")),
    )

    chain: Mapped[PipelineChain] = mapped_column(
        vocabulary(PipelineChain, "pipeline_chain"), nullable=False
    )
    trigger: Mapped[PipelineTrigger] = mapped_column(
        vocabulary(PipelineTrigger, "pipeline_trigger"), nullable=False
    )
    status: Mapped[PipelineRunStatus] = mapped_column(
        vocabulary(PipelineRunStatus, "pipeline_run_status"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stage_counts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    backlog: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    failed_stages: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
```

In `models/__init__.py`, add the import and the `__all__` entry, keeping both
alphabetical:

```python
from episignal_backend.models.pipeline import PipelineRun
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/backend/tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/models packages/backend/tests/test_models.py STATUS.md
git commit -m "feat: model a pipeline run"
```

---

### Task 8: Migration `20260828_0008_pipeline_runs`

**Files:**
- Create: `database/migrations/versions/20260828_0008_pipeline_runs.py`

- [ ] **Step 1: Write the migration**

Follow `database/migrations/versions/20260828_0007_event_scores.py` exactly for
header and revision style.

```python
"""create pipeline_runs

Revision ID: 20260828_0008
Revises: 20260828_0007
Create Date: 2026-08-28

Records one row per execution of one chain: when it started, what each stage
did, how deep the backlog was afterwards, and the publication-time window
discovery actually asked GDELT for. The window columns are what the next run
reads to compute its own, which is what makes a missed day recoverable.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260828_0008"
down_revision: str | None = "20260828_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "chain",
            sa.Enum("daily", name="pipeline_chain", native_enum=False, create_constraint=True),
            nullable=False,
        ),
        sa.Column(
            "trigger",
            sa.Enum(
                "scheduled",
                "manual",
                name="pipeline_trigger",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "succeeded",
                "failed",
                name="pipeline_run_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "stage_counts",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "backlog",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "failed_stages",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id", name="pk_pipeline_runs"),
    )
    op.create_index(
        "ix_pipeline_runs_chain_started_at",
        "pipeline_runs",
        ["chain", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_runs_chain_started_at", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
```

- [ ] **Step 2: Check it against the model rather than the database**

The live database is task 18. Here, confirm the model and the migration agree on
column names and nullability by reading both side by side. Every column in
`models/pipeline.py` must appear in the migration with the same name, type, and
`nullable`.

Run: `uv run pytest packages/backend/tests/test_models.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add database/migrations/versions/20260828_0008_pipeline_runs.py STATUS.md
git commit -m "feat: add the pipeline_runs migration"
```

---

### Task 9: The schema check knows the new table

**Files:**
- Modify: `packages/backend/src/episignal_backend/schema_check.py:18-29`
- Test: `packages/backend/tests/test_schema_check.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_schema_check.py`:

```python
def test_the_schema_check_expects_the_pipeline_runs_table() -> None:
    from episignal_backend.schema_check import EXPECTED_TABLES

    assert "pipeline_runs" in EXPECTED_TABLES


def test_a_database_without_pipeline_runs_is_reported_as_missing_it() -> None:
    from episignal_backend.schema_check import EXPECTED_TABLES, missing_tables

    present = {table for table in EXPECTED_TABLES if table != "pipeline_runs"}

    assert missing_tables(present) == ["pipeline_runs"]
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/backend/tests/test_schema_check.py -v`
Expected: FAIL, `assert 'pipeline_runs' in EXPECTED_TABLES`

- [ ] **Step 3: Write the implementation**

Add `"pipeline_runs",` to the end of the `EXPECTED_TABLES` tuple in
`schema_check.py`.

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/backend/tests/test_schema_check.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/schema_check.py packages/backend/tests/test_schema_check.py STATUS.md
git commit -m "feat: expect pipeline_runs in the live schema report"
```

---

### Task 10: The repository

**Files:**
- Create: `packages/backend/src/episignal_backend/schedule/repository.py`
- Test: `packages/backend/tests/test_schedule_repository.py`

The `FakeSession` pattern is at the top of
`packages/backend/tests/test_event_repository.py`. Copy it; do not import it.

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from episignal_backend.db.types import PipelineChain, PipelineRunStatus, PipelineTrigger
from episignal_backend.schedule.documents import DiscoveryWindow, StageName
from episignal_backend.schedule.protocol import PipelineRunRepository
from episignal_backend.schedule.repository import (
    PIPELINE_LOCK_KEY,
    SqlAlchemyPipelineRunRepository,
)

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one(self) -> Any:
        return self._value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def all(self) -> Any:
        return self._value

    def tuples(self) -> "FakeResult":
        return self


class FakeSession:
    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = results or []
        self.executed: list[Any] = []
        self.added: list[Any] = []
        self.flushed = 0

    def execute(self, statement: Any, *args: Any) -> Any:
        self.executed.append(statement)
        return self._results.pop(0) if self._results else FakeResult(None)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        self.flushed += 1


def test_the_repository_satisfies_the_protocol() -> None:
    assert isinstance(
        SqlAlchemyPipelineRunRepository(FakeSession()), PipelineRunRepository
    )


def test_taking_the_lock_asks_postgres_and_reports_the_answer() -> None:
    session = FakeSession([FakeResult(True)])
    repository = SqlAlchemyPipelineRunRepository(session)

    assert repository.try_lock() is True
    assert "pg_try_advisory_lock" in str(session.executed[0])


def test_a_lock_already_held_is_reported_as_false() -> None:
    repository = SqlAlchemyPipelineRunRepository(FakeSession([FakeResult(False)]))

    assert repository.try_lock() is False


def test_unlocking_without_the_lock_does_not_ask_postgres() -> None:
    session = FakeSession()
    repository = SqlAlchemyPipelineRunRepository(session)

    repository.unlock()

    assert session.executed == []


def test_the_lock_key_is_stable_across_processes() -> None:
    # Two processes must ask for the same key or the lock protects nothing.
    assert isinstance(PIPELINE_LOCK_KEY, int)
    assert PIPELINE_LOCK_KEY == 7_284_015_531


def test_starting_a_run_adds_a_running_row_carrying_the_window() -> None:
    session = FakeSession()
    repository = SqlAlchemyPipelineRunRepository(session)

    repository.start_run(
        chain=PipelineChain.DAILY,
        trigger=PipelineTrigger.SCHEDULED,
        started_at=NOW,
        window=DiscoveryWindow(start=NOW, end=NOW),
    )

    assert len(session.added) == 1
    row = session.added[0]
    assert row.status == PipelineRunStatus.RUNNING
    assert row.trigger == PipelineTrigger.SCHEDULED
    assert row.started_at == NOW
    assert row.window_start == NOW
    assert row.finished_at is None
    # Flushed so the row exists before any stage runs.
    assert session.flushed == 1


def test_starting_a_run_without_a_window_leaves_both_window_columns_null() -> None:
    session = FakeSession()
    repository = SqlAlchemyPipelineRunRepository(session)

    repository.start_run(
        chain=PipelineChain.DAILY,
        trigger=PipelineTrigger.MANUAL,
        started_at=NOW,
        window=None,
    )

    assert session.added[0].window_start is None
    assert session.added[0].window_end is None


def test_finishing_a_run_writes_the_counts_the_stages_reported() -> None:
    session = FakeSession()
    repository = SqlAlchemyPipelineRunRepository(session)
    run_id = uuid4()

    repository.finish_run(
        run_id,
        status=PipelineRunStatus.FAILED,
        finished_at=NOW,
        stage_counts={"geocode": {"located": 4}},
        backlog={"geocoded": 12},
        failed_stages=[StageName.EXTRACT],
    )

    statement = str(session.executed[0])
    assert "UPDATE pipeline_runs" in statement


def test_the_backlog_is_counted_by_processing_status() -> None:
    session = FakeSession([FakeResult([("geocoded", 12), ("matched", 3)])])
    repository = SqlAlchemyPipelineRunRepository(session)

    assert repository.backlog_depth() == {"geocoded": 12, "matched": 3}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/backend/tests/test_schedule_repository.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'episignal_backend.schedule.repository'`

- [ ] **Step 3: Write the implementation**

```python
"""The only module in `schedule/` that imports SQLAlchemy.

The advisory lock is session-level, not transaction-level: it is not released by
a rollback, and it dies with the connection. A killed run therefore cannot leave
the pipeline permanently locked, and a rolled-back stage cannot silently hand
the lock to a second process mid-chain.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from episignal_backend.db.types import PipelineChain, PipelineRunStatus, PipelineTrigger
from episignal_backend.models import PipelineRun, Signal
from episignal_backend.schedule.documents import DiscoveryWindow, StageName

# Arbitrary but fixed. Two processes must ask for the same key or the lock
# protects nothing, so this constant is never computed and never configured.
PIPELINE_LOCK_KEY = 7_284_015_531


class SqlAlchemyPipelineRunRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._locked = False

    def try_lock(self) -> bool:
        taken = bool(
            self._session.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": PIPELINE_LOCK_KEY}
            ).scalar_one()
        )
        self._locked = taken
        return taken

    def unlock(self) -> None:
        if not self._locked:
            return
        self._session.execute(
            text("SELECT pg_advisory_unlock(:key)"), {"key": PIPELINE_LOCK_KEY}
        )
        self._locked = False

    def last_window_end(self, chain: PipelineChain) -> datetime | None:
        return self._session.execute(
            select(PipelineRun.window_end)
            .where(
                PipelineRun.chain == chain,
                PipelineRun.window_end.is_not(None),
                PipelineRun.status != PipelineRunStatus.RUNNING,
            )
            .order_by(PipelineRun.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    def start_run(
        self,
        *,
        chain: PipelineChain,
        trigger: PipelineTrigger,
        started_at: datetime,
        window: DiscoveryWindow | None,
    ) -> UUID:
        run = PipelineRun(
            chain=chain,
            trigger=trigger,
            status=PipelineRunStatus.RUNNING,
            started_at=started_at,
            window_start=window.start if window else None,
            window_end=window.end if window else None,
        )
        self._session.add(run)
        # Flushed, not committed: the row must exist before the first stage so a
        # killed run leaves evidence, and the caller owns the transaction.
        self._session.flush()
        return run.id

    def finish_run(
        self,
        run_id: UUID,
        *,
        status: PipelineRunStatus,
        finished_at: datetime,
        stage_counts: dict[str, dict[str, int]],
        backlog: dict[str, int],
        failed_stages: list[StageName],
    ) -> None:
        self._session.execute(
            update(PipelineRun)
            .where(PipelineRun.id == run_id)
            .values(
                status=status,
                finished_at=finished_at,
                stage_counts=stage_counts,
                backlog=backlog,
                failed_stages=[str(stage) for stage in failed_stages],
            )
        )

    def backlog_depth(self) -> dict[str, int]:
        rows = self._session.execute(
            select(Signal.processing_status, func.count(Signal.id)).group_by(
                Signal.processing_status
            )
        ).all()
        return {str(status): int(count) for status, count in rows}
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/backend/tests/test_schedule_repository.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/schedule/repository.py packages/backend/tests/test_schedule_repository.py STATUS.md
git commit -m "feat: record pipeline runs and serialise them with an advisory lock"
```

---

### Task 11: Settings

**Files:**
- Modify: `packages/backend/src/episignal_backend/config.py:104` (after the event settings block)
- Test: `packages/backend/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_config.py`. That file has no helper: it
constructs `Settings` directly with `_env_file=None` and the `type: ignore`
comments pydantic-settings needs. Match it exactly.

```python
def test_the_catch_up_clamp_defaults_to_seven_days() -> None:
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql://user:secret@host/db",  # type: ignore[arg-type]
        _env_file=None,
    )

    assert settings.pipeline_catch_up_max_minutes == 10080


def test_the_default_chain_is_daily() -> None:
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql://user:secret@host/db",  # type: ignore[arg-type]
        _env_file=None,
    )

    assert settings.pipeline_chain == "daily"


def test_a_catch_up_clamp_shorter_than_the_query_window_is_refused() -> None:
    # A clamp inside the window would make the very first run ask for less than
    # the window it was configured with, which no later run ever repairs.
    with pytest.raises(ValidationError):
        Settings(  # type: ignore[call-arg]
            database_url="postgresql://user:secret@host/db",  # type: ignore[arg-type]
            gdelt_query_window_minutes=1500,
            pipeline_catch_up_max_minutes=600,
            _env_file=None,
        )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/backend/tests/test_config.py -v`
Expected: FAIL, `AttributeError: 'Settings' object has no attribute 'pipeline_catch_up_max_minutes'`

- [ ] **Step 3: Write the implementation**

In `config.py`, after `event_match_stale`:

```python
    # Seven days. Bounds the query issued after a long gap: a laptop closed for
    # a month asks for a week, not a month GDELT would refuse.
    pipeline_catch_up_max_minutes: int = Field(default=10080, ge=1, le=43200)
    pipeline_chain: Literal["daily"] = "daily"
```

And with the other `model_validator`s:

```python
    @model_validator(mode="after")
    def catch_up_covers_the_query_window(self) -> "Settings":
        if self.pipeline_catch_up_max_minutes < self.gdelt_query_window_minutes:
            raise ValueError(
                "EPISIGNAL_PIPELINE_CATCH_UP_MAX_MINUTES must cover "
                "EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES"
            )
        return self
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/backend/tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/config.py packages/backend/tests/test_config.py STATUS.md
git commit -m "feat: add the scheduler settings and the catch-up clamp"
```

---

### Task 12: The stage adapters

Each stage calls the same domain function its runner already calls. Do not call
the runners' `main()` or `_run()`: those parse argv, print, and return exit
codes, none of which belong inside a chain.

**Files:**
- Create: `packages/backend/src/episignal_backend/schedule/stages.py`
- Test: `packages/backend/tests/test_schedule_stages.py`

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime

from episignal_backend.schedule.chains import DAILY_CHAIN
from episignal_backend.schedule.documents import DiscoveryWindow, StageName
from episignal_backend.schedule.stages import build_stage_runners

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def test_every_stage_in_the_daily_chain_has_a_runner() -> None:
    runners = build_stage_runners(window=DiscoveryWindow(start=NOW, end=NOW))

    for stage in DAILY_CHAIN:
        assert stage in runners


def test_no_runner_is_called_while_the_mapping_is_being_built() -> None:
    # Building the mapping must not open a session, read settings, or construct
    # an OpenRouter client, or importing the module would need a database.
    runners = build_stage_runners(window=DiscoveryWindow(start=NOW, end=NOW))

    assert callable(runners[StageName.EXTRACT])


def test_the_mapping_covers_exactly_the_stage_names() -> None:
    runners = build_stage_runners(window=DiscoveryWindow(start=NOW, end=NOW))

    assert set(runners) == set(StageName)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/backend/tests/test_schedule_stages.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'episignal_backend.schedule.stages'`

- [ ] **Step 3: Write the implementation**

```python
"""Each stage, as the chain calls it.

Every function here calls the same domain function the matching runner calls.
The runners' own `main` and `_run` parse argv, print, and return exit codes,
none of which belong inside a chain.

Each stage opens its own session. That is deliberate: a stage that fails must
not roll back the stages that already succeeded, and the advisory lock is held
on a different connection for the whole run.
"""

from collections.abc import Mapping

from episignal_backend.ai.classify import run_classification
from episignal_backend.ai.extract import run_extraction
from episignal_backend.ai.ladder import Guards
from episignal_backend.ai.openrouter import OpenRouterChatModel
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.events.assemble import run_event_assembly
from episignal_backend.events.repository import SqlAlchemyEventRepository
from episignal_backend.geocode.locate import run_geocoding
from episignal_backend.geocode.repository import (
    SqlAlchemyGazetteerRepository,
    SqlAlchemyGeocodeRepository,
)
from episignal_backend.ingestion.dedupe import DedupeThresholds, run_dedupe
from episignal_backend.ingestion.discovery import run_discovery, run_retry
from episignal_backend.ingestion.ecdc_epi import EcdcEpiConnector
from episignal_backend.ingestion.gdelt.api import GdeltDocClient
from episignal_backend.ingestion.gdelt.article import ArticleFetcher
from episignal_backend.ingestion.gdelt.connector import GdeltConnector
from episignal_backend.ingestion.pipeline import run_ingestion
from episignal_backend.ingestion.protocol import SourceConnector
from episignal_backend.ingestion.repository import (
    SqlAlchemyDedupeRepository,
    SqlAlchemyDiscoveryRepository,
    SqlAlchemySignalRepository,
)
from episignal_backend.ingestion.who_don import WhoDonConnector
from episignal_backend.schedule.documents import DiscoveryWindow, StageName
from episignal_backend.schedule.run import StageRunner


def _ingest(connector: SourceConnector) -> Mapping[str, int]:
    with session_scope() as session:
        result = run_ingestion(
            SqlAlchemySignalRepository(session), connector, since=None
        )
    return {
        "inserted": result.inserted,
        "skipped": result.skipped,
        "rejected": result.rejected,
        "failed": result.failed,
    }


def _discover(window: DiscoveryWindow) -> Mapping[str, int]:
    settings = get_settings()
    connector = GdeltConnector(
        search=GdeltDocClient(),
        fetcher=ArticleFetcher(
            delay_seconds=settings.gdelt_article_delay_seconds,
            user_agent=settings.gdelt_user_agent,
            timeout_seconds=settings.gdelt_article_timeout_seconds,
        ),
    )
    with session_scope() as session:
        repository = SqlAlchemyDiscoveryRepository(session)
        # Retry first: a stub is a page already known to be wanted, so it has a
        # better claim on the run budget than an article not yet seen.
        retried = run_retry(
            repository,
            connector,
            max_attempts=settings.gdelt_max_retrieval_attempts,
            batch_size=settings.gdelt_retry_batch_size,
        )
        discovered = run_discovery(
            repository,
            connector,
            now=window.end,
            window_minutes=window.minutes,
            max_articles=settings.gdelt_max_articles_per_run,
        )
    return {
        "retried": retried.attempted,
        "promoted": retried.promoted,
        "window_minutes": window.minutes,
        "rules": discovered.rules_run,
        "rules_failed": discovered.rules_failed,
        "discovered": discovered.discovered,
        "duplicate": discovered.duplicate,
        "rejected": discovered.rejected,
        "stored": discovered.stored,
        "failed": discovered.failed,
    }


def _dedupe() -> Mapping[str, int]:
    settings = get_settings()
    with session_scope() as session:
        result = run_dedupe(
            SqlAlchemyDedupeRepository(session),
            thresholds=DedupeThresholds(
                title=settings.stage0_title_similarity,
                body=settings.stage0_body_similarity,
                shingle_size=settings.stage0_shingle_size,
            ),
            window_hours=settings.stage0_candidate_window_hours,
            batch_size=settings.stage0_batch_size,
        )
    return {
        "examined": result.examined,
        "primaries": result.primaries,
        "duplicates": result.duplicates,
        "failed": result.failed,
    }


def _extract() -> Mapping[str, int]:
    settings = get_settings()
    if settings.openrouter_api_key is None:
        raise RuntimeError("EPISIGNAL_OPENROUTER_API_KEY is not set")

    model = OpenRouterChatModel(
        settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        timeout_seconds=settings.ai_request_timeout_seconds,
        max_attempts=settings.ai_max_attempts_per_tier,
    )
    guards = Guards(
        max_requests=settings.ai_max_requests_per_run,
        max_cost_usd=settings.ai_max_cost_usd_per_run,
    )

    with session_scope() as session:
        repository = SqlAlchemyAiRepository(session)
        classified = run_classification(
            repository,
            model,
            guards=guards,
            batch_size=settings.ai_batch_size,
            limit=settings.ai_signal_batch_limit,
            max_tier=settings.ai_max_tier,
            max_input_characters=settings.ai_max_input_characters,
        )
        extracted = run_extraction(
            repository,
            model,
            guards=guards,
            limit=settings.ai_signal_batch_limit,
            max_tier=settings.ai_max_tier,
            max_input_characters=settings.ai_max_input_characters,
            min_confidence=settings.ai_min_confidence,
        )
    return {
        "classified": classified.examined,
        "relevant": classified.relevant,
        "irrelevant": classified.irrelevant,
        "extracted": extracted.extracted,
        "review": classified.reviewed + extracted.reviewed,
        "unavailable": classified.unavailable + extracted.unavailable,
        "requests": classified.requests + extracted.requests,
    }


def _geocode() -> Mapping[str, int]:
    settings = get_settings()
    limit = min(settings.geocode_batch_size, settings.geocode_max_signals_per_run)
    with session_scope() as session:
        result = run_geocoding(
            SqlAlchemyGeocodeRepository(session),
            SqlAlchemyGazetteerRepository(session),
            limit=limit,
            source=settings.gazetteer_source,
            stale=False,
        )
    return {
        "examined": result.examined,
        "located": result.located,
        "unresolved": result.unresolved,
        "locations": result.locations,
    }


def _match() -> Mapping[str, int]:
    settings = get_settings()
    with session_scope() as session:
        summary = run_event_assembly(
            SqlAlchemyEventRepository(session),
            limit=settings.event_match_batch_size,
            stale=False,
            cluster_window_days=settings.event_cluster_window_days,
            cluster_distance_km=settings.event_cluster_distance_km,
            match_threshold=settings.event_match_threshold,
            match_recency_days=settings.event_match_recency_days,
            match_distance_km=settings.event_match_distance_km,
        )
    return {
        "seen": summary.signals_seen,
        "clusters": summary.clusters_built,
        "created": summary.events_created,
        "attached": summary.signals_attached,
        "refused": summary.signals_refused,
        "unclusterable": summary.unclusterable,
    }


def build_stage_runners(*, window: DiscoveryWindow) -> dict[StageName, StageRunner]:
    """Map each stage to a callable. Nothing here runs until the chain calls it."""
    return {
        StageName.INGEST_WHO: lambda: _ingest(WhoDonConnector()),
        StageName.INGEST_ECDC: lambda: _ingest(EcdcEpiConnector()),
        StageName.DISCOVER: lambda: _discover(window),
        StageName.DEDUPE: _dedupe,
        StageName.EXTRACT: _extract,
        StageName.GEOCODE: _geocode,
        StageName.MATCH: _match,
    }
```

If any import path above is wrong, fix it against the matching runner in
`packages/backend/src/episignal_backend/` — that runner is the authority, not
this plan.

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/backend/tests/test_schedule_stages.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/schedule/stages.py packages/backend/tests/test_schedule_stages.py STATUS.md
git commit -m "feat: adapt each existing runner path into a chain stage"
```

---

### Task 13: The runner

**Files:**
- Create: `packages/backend/src/episignal_backend/pipeline_runner.py`
- Test: `packages/backend/tests/test_pipeline_runner.py`

Model the argv handling on `packages/backend/src/episignal_backend/event_runner.py`,
including the `[arg for arg in argv if arg != "--"]` filter that lets
`pnpm pipeline:run -- --only match` work.

- [ ] **Step 1: Write the failing test**

```python
from episignal_backend.pipeline_runner import parse_arguments
from episignal_backend.schedule.documents import StageName


def test_a_bare_invocation_runs_the_whole_chain() -> None:
    arguments = parse_arguments([])

    assert arguments.only is None
    assert arguments.trigger == "manual"


def test_pnpm_double_dash_is_not_mistaken_for_an_argument() -> None:
    arguments = parse_arguments(["--", "--only", "match"])

    assert arguments.only == StageName.MATCH


def test_a_scheduled_run_says_so() -> None:
    # This is how "did Task Scheduler actually fire" is answerable later.
    assert parse_arguments(["--trigger", "scheduled"]).trigger == "scheduled"


def test_only_accepts_a_real_stage_name() -> None:
    import pytest

    with pytest.raises(SystemExit):
        parse_arguments(["--only", "publish"])
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/backend/tests/test_pipeline_runner.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'episignal_backend.pipeline_runner'`

- [ ] **Step 3: Write the implementation**

```python
"""Entry point for `pnpm pipeline:run`.

Counts and stage names only. The connection string, the article text, and the
API key never reach stdout or stderr; a stage failure is reported as the
exception's type and nothing about what was in it.

Re-running is safe: every stage selects its own backlog by processing_status. A
second run started while one is in progress takes no lock, prints that a run is
in progress, and exits 0 — a skipped overlap is the correct outcome.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.db.types import PipelineChain, PipelineRunStatus, PipelineTrigger
from episignal_backend.schedule.chains import chain_for
from episignal_backend.schedule.documents import ChainOutcome, StageName
from episignal_backend.schedule.repository import SqlAlchemyPipelineRunRepository
from episignal_backend.schedule.run import run_chain
from episignal_backend.schedule.stages import build_stage_runners
from episignal_backend.schedule.window import catch_up_window


@dataclass(frozen=True)
class Arguments:
    only: StageName | None
    trigger: str


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="pipeline_run",
        description="Run the daily pipeline chain once.",
    )
    parser.add_argument(
        "--only",
        type=StageName,
        choices=list(StageName),
        default=None,
        help="Run one stage instead of the whole chain.",
    )
    parser.add_argument(
        "--trigger",
        choices=["scheduled", "manual"],
        default="manual",
        help="Who started this run. Task Scheduler passes scheduled.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(only=parsed.only, trigger=parsed.trigger)


def _print(outcome: ChainOutcome, backlog: dict[str, int]) -> None:
    for stage in outcome.outcomes:
        if stage.ok:
            counts = " ".join(f"{key}={value}" for key, value in stage.counts.items())
            print(f"{stage.stage} ok {counts}".rstrip())
        else:
            print(f"{stage.stage} failed ({stage.error})")
    print("backlog " + " ".join(f"{key}={value}" for key, value in sorted(backlog.items())))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    settings = get_settings()
    chain_name = PipelineChain(settings.pipeline_chain)
    chain = chain_for(settings.pipeline_chain)
    if arguments.only is not None:
        chain = (arguments.only,)

    try:
        with session_scope() as session:
            repository = SqlAlchemyPipelineRunRepository(session)
            if not repository.try_lock():
                print("A pipeline run is already in progress; nothing to do.")
                return 0

            try:
                started_at = datetime.now(UTC)
                window = catch_up_window(
                    now=started_at,
                    last_window_end=repository.last_window_end(chain_name),
                    default_minutes=settings.gdelt_query_window_minutes,
                    max_minutes=settings.pipeline_catch_up_max_minutes,
                )
                run_id = repository.start_run(
                    chain=chain_name,
                    trigger=PipelineTrigger(arguments.trigger),
                    started_at=started_at,
                    window=window if StageName.DISCOVER in chain else None,
                )

                outcome = run_chain(chain, build_stage_runners(window=window))
                backlog = repository.backlog_depth()

                repository.finish_run(
                    run_id,
                    status=(
                        PipelineRunStatus.SUCCEEDED
                        if outcome.ok
                        else PipelineRunStatus.FAILED
                    ),
                    finished_at=datetime.now(UTC),
                    stage_counts={
                        str(item.stage): dict(item.counts) for item in outcome.outcomes
                    },
                    backlog=backlog,
                    failed_stages=list(outcome.failed_stages),
                )
            finally:
                repository.unlock()
    except Exception as error:
        print(
            f"The pipeline run failed before completing ({type(error).__name__}). "
            "Check the database and the migration state.",
            file=sys.stderr,
        )
        return 1

    _print(outcome, backlog)
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run it and watch it pass**

Run: `uv run pytest packages/backend/tests/test_pipeline_runner.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/pipeline_runner.py packages/backend/tests/test_pipeline_runner.py STATUS.md
git commit -m "feat: add the pipeline runner"
```

---

### Task 14: The script and the shell wrapper

**Files:**
- Modify: `package.json` (scripts block, after `match:events`)
- Create: `scripts/run-pipeline.ps1`

- [ ] **Step 1: Add the script**

In `package.json`, after the `match:events` line:

```json
    "pipeline:run": "uv run --package episignal-backend python -m episignal_backend.pipeline_runner",
```

- [ ] **Step 2: Write the wrapper**

`scripts/match-events.ps1` is the model: `[CmdletBinding()]`, a `param` block,
`$ErrorActionPreference = 'Stop'`, an `$argsList` array, and a direct
`uv run --package episignal-backend python -m ...` call — not `corepack pnpm`.
Match that. It must pass `--trigger scheduled`, because distinguishing a run
Task Scheduler fired from one you started by hand is the whole point of the
wrapper.

```powershell
[CmdletBinding()]
param(
    [ValidateSet('ingest_who', 'ingest_ecdc', 'discover', 'dedupe', 'extract', 'geocode', 'match')]
    [string]$Only
)

$ErrorActionPreference = 'Stop'

$argsList = @("--trigger", "scheduled")
if ($Only) { $argsList += "--only", $Only }

& uv run --package episignal-backend python -m episignal_backend.pipeline_runner @argsList
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
```

- [ ] **Step 3: Check the command resolves**

Run: `corepack pnpm pipeline:run -- --help`
Expected: argparse usage text naming `--only` and `--trigger`. It must not touch
the database, because `--help` exits before `main` reads settings.

- [ ] **Step 4: Commit**

```bash
git add package.json scripts/run-pipeline.ps1 STATUS.md
git commit -m "feat: add the pipeline script and its scheduled wrapper"
```

---

### Task 15: The environment example

**Files:**
- Modify: `apps/api/.env.example` — the only env example the repository tracks, and the file `Settings.model_config` points `env_file` at

- [ ] **Step 1: Add the MVP block**

```dotenv
# Scheduler. The pipeline runs once a day, so discovery's window must cover a
# day: at the 20-minute default a daily run would see 20 minutes out of 1440.
# The extra 60 minutes is overlap, so scheduler jitter cannot open a gap.
EPISIGNAL_GDELT_POLL_INTERVAL_MINUTES=1440
EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES=1500
# Intake matched to what extraction can drain in the same run. Raise both
# together or the un-extracted backlog grows every day.
EPISIGNAL_GDELT_MAX_ARTICLES_PER_RUN=100
EPISIGNAL_PIPELINE_CATCH_UP_MAX_MINUTES=10080
```

- [ ] **Step 2: Commit**

```bash
git add apps/api/.env.example STATUS.md
git commit -m "docs: document the daily cadence settings"
```

---

### Task 16: The seam guard

**Files:**
- Create: `packages/backend/tests/test_schedule_seams.py`

- [ ] **Step 1: Write the test**

Model it on `packages/backend/tests/test_event_seams.py`.

```python
import ast
from pathlib import Path

import pytest

SCHEDULE = Path(__file__).parents[1] / "src" / "episignal_backend" / "schedule"
PURE_MODULES = ("documents.py", "chains.py", "window.py", "protocol.py", "run.py")


def _imported_top_levels(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


@pytest.mark.parametrize("name", PURE_MODULES)
def test_a_pure_module_imports_no_database_driver(name: str) -> None:
    imports = _imported_top_levels(SCHEDULE / name)
    assert "sqlalchemy" not in imports
    assert "geoalchemy2" not in imports


@pytest.mark.parametrize("name", PURE_MODULES)
def test_a_pure_module_touches_no_network(name: str) -> None:
    imports = _imported_top_levels(SCHEDULE / name)
    assert "httpx" not in imports
    assert "requests" not in imports


def test_only_the_repository_imports_sqlalchemy() -> None:
    importers = {
        path.name
        for path in SCHEDULE.glob("*.py")
        if "sqlalchemy" in _imported_top_levels(path)
    }
    assert importers == {"repository.py"}


def test_the_runner_prints_no_connection_string() -> None:
    runner = SCHEDULE.parent / "pipeline_runner.py"
    source = runner.read_text(encoding="utf-8")

    assert "database_url" not in source
    assert "get_secret_value" not in source
```

- [ ] **Step 2: Run it**

Run: `uv run pytest packages/backend/tests/test_schedule_seams.py -v`
Expected: PASS, 13 tests. If `test_only_the_repository_imports_sqlalchemy`
fails, a pure module has grown a driver import — fix the module, not the test.

- [ ] **Step 3: Commit**

```bash
git add packages/backend/tests/test_schedule_seams.py STATUS.md
git commit -m "test: guard the scheduler's seams"
```

---

### Task 17: The scheduling document

**Files:**
- Create: `docs/architecture/scheduling.md`

- [ ] **Step 1: Write it**

It must cover, in prose a person can follow at a terminal:

1. What `pnpm pipeline:run` does, and that it exits 0 when a run is already in
   progress.
2. Registering the Windows Task Scheduler entry pointing at
   `scripts/run-pipeline.ps1`, daily, with **Run whether user is logged on or
   not** and **Start the task as soon as possible after a scheduled start is
   missed** both enabled — a laptop asleep at the scheduled time is the normal
   case, not the exception.
3. That the catch-up window makes a missed day recoverable up to seven days, and
   that a longer gap is clamped and visibly recorded in `pipeline_runs`.
4. How to read the last few runs:

```sql
SELECT started_at, finished_at, status, failed_stages, backlog
FROM pipeline_runs
ORDER BY started_at DESC
LIMIT 7;
```

5. That a `running` row with a null `finished_at` means a killed run, and that
   nothing cleans those up.
6. Retrying one stage by hand: `corepack pnpm pipeline:run -- --only extract`.

- [ ] **Step 2: Commit**

```bash
git add docs/architecture/scheduling.md STATUS.md
git commit -m "docs: document the daily scheduled run"
```

---

### Task 18: Live verification and the completion report

This is the only task that touches the database, the network, or a model.

**Files:**
- Create: `docs/reports/2026-08-28-subproject-l-report.md`
- Modify: `STATUS.md` (verified baseline)

- [ ] **Step 1: Migrate**

Run: `corepack pnpm db:migrate`
Expected: `20260828_0008` applied. Then `corepack pnpm db:check` prints
`database=up postgis=up`, and
`uv run --package episignal-backend python -m episignal_backend.schema_check`
reports `"missing_tables": []`.

- [ ] **Step 2: Run the chain once**

Run: `corepack pnpm pipeline:run`
Expected: seven stage lines then a backlog line. Record the real output.

- [ ] **Step 3: Prove the lock**

Start a run and, while it is going, start a second in another terminal.
Expected: the second prints `A pipeline run is already in progress; nothing to
do.` and exits 0. Record both.

- [ ] **Step 4: Prove the window carried forward**

Run:

```bash
uv run --package episignal-api python -c "from sqlalchemy import text; from episignal_backend.db.session import connection_scope; c=connection_scope().__enter__(); print(c.execute(text('SELECT started_at, status, window_start, window_end, failed_stages FROM pipeline_runs ORDER BY started_at DESC LIMIT 3')).all())"
```

Expected: the second run's `window_start` equals the first run's `window_end`.
This is the acceptance criterion for the catch-up window; if it does not hold,
the item is not done.

- [ ] **Step 5: Run the gate**

Run: `corepack pnpm verify`
Expected: exit 0.

- [ ] **Step 6: Write the report and update the baseline**

Follow `docs/reports/2026-08-28-subproject-d2a-report.md`. Quote the real,
untruncated output of every command above — the actual test counts, not a claim
that tests passed. `docs/agents/workflow.md` makes this the completion gate, and
it is not waived.

Update the **Verified baseline** table in `STATUS.md` to the commit the verify
run was performed at. This is the worker's job, not the planner's, and it was
missed on `D2a`.

- [ ] **Step 7: Commit and hand back**

```bash
git add docs/reports/2026-08-28-subproject-l-report.md STATUS.md
git commit -m "docs: sub-project L completion report"
```

Do not set `L` to `verified` in `ROADMAP.md`. That is the planner's, after the
gate is checked.

---

## Self-review notes

- Every stage name used in a later task (`ingest_who`, `ingest_ecdc`,
  `discover`, `dedupe`, `extract`, `geocode`, `match`) is the one defined in
  task 1 and ordered in task 2.
- `catch_up_window`'s four keyword arguments in task 3 are the four passed in
  task 13.
- `PipelineRunRepository`'s six methods in task 4 are the six implemented in
  task 10 and the six called in task 13.
- Task 4's test imports enums that task 5 creates. That order is called out in
  task 4 step 2.
- `StageRunner` is defined in task 6 (`run.py`) and imported by task 12
  (`stages.py`), which is why `stages.py` may import from `run.py` and not the
  other way round.
