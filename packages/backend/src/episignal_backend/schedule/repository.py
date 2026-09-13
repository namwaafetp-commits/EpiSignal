"""The only module in `schedule/` that imports SQLAlchemy.

The advisory lock is session-level, not transaction-level: it is not released by
a rollback, and it dies with the connection. A killed run therefore cannot leave
the pipeline permanently locked, and a rolled-back stage cannot silently hand
the lock to a second process mid-chain.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from episignal_backend.db.types import PipelineChain, PipelineRunStatus, PipelineTrigger
from episignal_backend.models import PipelineRun, Signal
from episignal_backend.schedule.documents import DiscoveryWindow, StageOutcome

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
        self._session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": PIPELINE_LOCK_KEY})
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
        stage_counts: dict[str, dict[str, Any]],
        backlog: dict[str, int],
        failed_stages: Sequence[StageOutcome],
    ) -> None:
        assert all(not item.ok for item in failed_stages), (
            "failed_stages must contain only failed outcomes"
        )
        self._session.execute(
            update(PipelineRun)
            .where(PipelineRun.id == run_id)
            .values(
                status=status,
                finished_at=finished_at,
                stage_counts=stage_counts,
                backlog=backlog,
                failed_stages=[
                    {
                        "stage": str(item.stage),
                        "error": item.error,
                        **(
                            {"error_category": item.error_category}
                            if item.error_category is not None
                            else {}
                        ),
                    }
                    for item in failed_stages
                ],
            )
        )

    def backlog_depth(self) -> dict[str, int]:
        rows = self._session.execute(
            select(Signal.processing_status, func.count(Signal.id)).group_by(
                Signal.processing_status
            )
        ).all()
        return {str(status): int(count) for status, count in rows}
