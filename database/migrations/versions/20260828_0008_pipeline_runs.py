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
