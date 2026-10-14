"""create best-effort structured pipeline health telemetry

Revision ID: 20260904_0022
Revises: 20260904_0021
Create Date: 2026-09-04

The health row is separate from event data and is linked one-to-one to the
existing pipeline run. Telemetry columns remain nullable when a stage or
instrumentation source did not provide a trustworthy value.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260904_0022"
down_revision: str | None = "20260904_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_health_runs",
        sa.Column(
            "pipeline_run_id",
            sa.Uuid(),
            sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=True),
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
        sa.Column("discovered", sa.Integer(), nullable=True),
        sa.Column("dedup_primary", sa.Integer(), nullable=True),
        sa.Column("deepseek_requested", sa.Integer(), nullable=True),
        sa.Column("deepseek_success", sa.Integer(), nullable=True),
        sa.Column("deepseek_relevant", sa.Integer(), nullable=True),
        sa.Column("retrieval_requested", sa.Integer(), nullable=True),
        sa.Column("retrieval_success", sa.Integer(), nullable=True),
        sa.Column("gemini_requested", sa.Integer(), nullable=True),
        sa.Column("gemini_success", sa.Integer(), nullable=True),
        sa.Column("grouping_requested", sa.Integer(), nullable=True),
        sa.Column("grouping_success", sa.Integer(), nullable=True),
        sa.Column("mistral_requested", sa.Integer(), nullable=True),
        sa.Column("mistral_success", sa.Integer(), nullable=True),
        sa.Column("new_events", sa.Integer(), nullable=True),
        sa.Column("updated_events", sa.Integer(), nullable=True),
        sa.Column("summarized_events", sa.Integer(), nullable=True),
        sa.Column("fatal_error_count", sa.Integer(), nullable=True),
        sa.Column(
            "error_categories",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("unknown_disease_rate", sa.Float(), nullable=True),
        sa.Column("no_location_rate", sa.Float(), nullable=True),
        sa.Column("new_event_rate", sa.Float(), nullable=True),
        sa.Column("matched_existing_event_rate", sa.Float(), nullable=True),
        sa.Column("duplicate_article_rate", sa.Float(), nullable=True),
        sa.Column("average_signals_per_event", sa.Float(), nullable=True),
        sa.Column("dashboard_response_ms", sa.Float(), nullable=True),
        sa.Column("endpoint_latency_ms", sa.Float(), nullable=True),
        sa.Column("db_query_duration_ms", sa.Float(), nullable=True),
        sa.Column(
            "unavailable_metrics",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("pipeline_run_id", name="pk_pipeline_health_runs"),
    )
    op.create_index(
        "ix_pipeline_health_runs_finished_at",
        "pipeline_health_runs",
        ["finished_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pipeline_health_runs_finished_at", table_name="pipeline_health_runs")
    op.drop_table("pipeline_health_runs")
