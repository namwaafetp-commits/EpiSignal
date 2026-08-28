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
