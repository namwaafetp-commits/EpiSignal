"""The storage boundary for scheduled pipeline runs.

`PipelineRunRepository` declares the contract between the chain and storage. The
repository owns the connection, the advisory lock, and the transaction: nothing
above it knows what a session is.

This module imports neither database driver nor httpx.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from episignal_backend.db.types import PipelineChain, PipelineRunStatus, PipelineTrigger
from episignal_backend.schedule.documents import DiscoveryWindow, StageOutcome


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
        failed_stages: Sequence[StageOutcome],
    ) -> None:
        """Close the row out with what every stage did."""
        ...

    def backlog_depth(self) -> dict[str, int]:
        """Count signals by processing_status, so a growing backlog is a recorded fact."""
        ...
