from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, text
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


class PipelineHealthRun(Base):
    """Best-effort structured health telemetry for one pipeline run."""

    __tablename__ = "pipeline_health_runs"
    __table_args__ = (Index("ix_pipeline_health_runs_finished_at", "finished_at"),)

    pipeline_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), primary_key=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_sec: Mapped[float | None] = mapped_column(Float)
    status: Mapped[PipelineRunStatus] = mapped_column(
        vocabulary(PipelineRunStatus, "pipeline_run_status"), nullable=False
    )
    discovered: Mapped[int | None] = mapped_column(Integer)
    dedup_primary: Mapped[int | None] = mapped_column(Integer)
    deepseek_requested: Mapped[int | None] = mapped_column(Integer)
    deepseek_success: Mapped[int | None] = mapped_column(Integer)
    deepseek_relevant: Mapped[int | None] = mapped_column(Integer)
    retrieval_requested: Mapped[int | None] = mapped_column(Integer)
    retrieval_success: Mapped[int | None] = mapped_column(Integer)
    gemini_requested: Mapped[int | None] = mapped_column(Integer)
    gemini_success: Mapped[int | None] = mapped_column(Integer)
    grouping_requested: Mapped[int | None] = mapped_column(Integer)
    grouping_success: Mapped[int | None] = mapped_column(Integer)
    mistral_requested: Mapped[int | None] = mapped_column(Integer)
    mistral_success: Mapped[int | None] = mapped_column(Integer)
    new_events: Mapped[int | None] = mapped_column(Integer)
    updated_events: Mapped[int | None] = mapped_column(Integer)
    summarized_events: Mapped[int | None] = mapped_column(Integer)
    fatal_error_count: Mapped[int | None] = mapped_column(Integer)
    error_categories: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    unknown_disease_rate: Mapped[float | None] = mapped_column(Float)
    no_location_rate: Mapped[float | None] = mapped_column(Float)
    new_event_rate: Mapped[float | None] = mapped_column(Float)
    matched_existing_event_rate: Mapped[float | None] = mapped_column(Float)
    duplicate_article_rate: Mapped[float | None] = mapped_column(Float)
    average_signals_per_event: Mapped[float | None] = mapped_column(Float)
    dashboard_response_ms: Mapped[float | None] = mapped_column(Float)
    endpoint_latency_ms: Mapped[float | None] = mapped_column(Float)
    db_query_duration_ms: Mapped[float | None] = mapped_column(Float)
    unavailable_metrics: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
