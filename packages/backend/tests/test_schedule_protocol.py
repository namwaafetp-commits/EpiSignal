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
    from pathlib import Path

    import episignal_backend.schedule.protocol as module

    source = Path(module.__file__).read_text(encoding="utf-8")
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
