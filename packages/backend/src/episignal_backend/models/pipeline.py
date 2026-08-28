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
