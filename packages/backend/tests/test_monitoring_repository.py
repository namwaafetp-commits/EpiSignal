from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from episignal_backend.db.base import Base
from episignal_backend.db.types import PipelineRunStatus, PipelineTrigger
from episignal_backend.models import PipelineHealthRun, PipelineRun
from episignal_backend.monitoring_repository import SqlAlchemyPipelineHealthRepository
from episignal_backend.operational_monitoring import PipelineHealthRecord, PipelineRunCoverageRecord

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def record() -> PipelineHealthRecord:
    return PipelineHealthRecord(
        run_id=uuid4(),
        started_at=NOW,
        finished_at=NOW,
        status=PipelineRunStatus.SUCCEEDED,
        discovered=4,
        error_categories={"TimeoutError": 1},
        unavailable_metrics={"endpoint_latency_ms": "not instrumented"},
    )


class FakeScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def scalars(self) -> "FakeScalarResult":
        return self

    def all(self) -> list[Any]:
        return self.rows


class FakeSession:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = rows or []
        self.added: list[Any] = []
        self.executed: list[Any] = []

    def merge(self, row: Any) -> Any:
        self.added.append(row)
        return row

    def execute(self, statement: Any) -> FakeScalarResult:
        self.executed.append(statement)
        if not self.rows:
            return FakeScalarResult([])
        result = self.rows.pop(0)
        return FakeScalarResult(result if isinstance(result, list) else [result])


def test_health_table_has_one_row_per_pipeline_run_and_nullable_telemetry() -> None:
    table = Base.metadata.tables["pipeline_health_runs"]

    assert list(table.primary_key.columns.keys()) == ["pipeline_run_id"]
    assert table.columns["pipeline_run_id"].nullable is False
    assert table.columns["finished_at"].nullable is True
    assert table.columns["unknown_disease_rate"].nullable is True
    assert table.columns["endpoint_latency_ms"].nullable is True


def test_repository_maps_record_without_touching_pipeline_or_event_tables() -> None:
    session = FakeSession()
    repository = SqlAlchemyPipelineHealthRepository(session)
    health = record()

    repository.record(health)

    row = session.added[0]
    assert isinstance(row, PipelineHealthRun)
    assert row.pipeline_run_id == health.run_id
    assert row.discovered == 4
    assert row.error_categories == {"TimeoutError": 1}
    assert row.unavailable_metrics == {"endpoint_latency_ms": "not instrumented"}
    assert row.__tablename__ == "pipeline_health_runs"


def test_repository_reads_recent_health_rows_with_one_query() -> None:
    session = FakeSession()
    repository = SqlAlchemyPipelineHealthRepository(session)

    rows = repository.recent_records(NOW)

    assert rows == ()
    assert len(session.executed) == 1
    assert "pipeline_health_runs" in str(session.executed[0])


def test_repository_reads_pipeline_trigger_for_slot_coverage() -> None:
    health = PipelineHealthRun(
        pipeline_run_id=uuid4(),
        started_at=NOW,
        finished_at=NOW,
        status=PipelineRunStatus.SUCCEEDED,
    )
    session = FakeSession([(health, PipelineTrigger.SCHEDULED, {"extract": {"duration_sec": 2.5}})])
    repository = SqlAlchemyPipelineHealthRepository(session)

    rows = repository.recent_records(NOW)

    assert rows[0].trigger is PipelineTrigger.SCHEDULED
    assert rows[0].stage_durations_sec == {"extract": 2.5}


def test_repository_reads_pipeline_runs_for_coverage_without_health_rows() -> None:
    pipeline_run = PipelineRun(
        id=uuid4(),
        started_at=NOW,
        status=PipelineRunStatus.RUNNING,
        trigger=PipelineTrigger.SCHEDULED,
    )
    session = FakeSession([[pipeline_run]])
    repository = SqlAlchemyPipelineHealthRepository(session)

    rows = repository.recent_pipeline_runs(NOW)

    assert len(rows) == 1
    assert isinstance(rows[0], PipelineRunCoverageRecord)
    assert rows[0].run_id == pipeline_run.id
    assert rows[0].finished_at is None
    assert rows[0].status is PipelineRunStatus.RUNNING
    assert rows[0].trigger is PipelineTrigger.SCHEDULED


def test_repository_reads_failed_pipeline_runs_for_coverage() -> None:
    failed = PipelineRun(
        id=uuid4(),
        started_at=NOW,
        finished_at=NOW,
        status=PipelineRunStatus.FAILED,
        trigger=PipelineTrigger.SCHEDULED,
    )
    session = FakeSession([[failed]])
    repository = SqlAlchemyPipelineHealthRepository(session)

    rows = repository.recent_pipeline_runs(NOW)

    assert rows[0].status is PipelineRunStatus.FAILED
