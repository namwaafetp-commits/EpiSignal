"""add aggregate Briefing popularity metrics"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260917_0026"
down_revision: str | None = "20260912_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_popularity_metrics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("impressions_unique", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("briefing_opens_unique", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("baseline_ctr", sa.Float(), nullable=True),
        sa.Column("smoothed_ctr", sa.Float(), nullable=True),
        sa.Column("engagement_score", sa.Float(), nullable=True),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_event_popularity_metrics"),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name="fk_event_popularity_metrics_event_id_events",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "impressions_unique >= 0 AND briefing_opens_unique >= 0",
            name="ck_event_popularity_metrics_non_negative_counts",
        ),
        sa.CheckConstraint(
            "baseline_ctr >= 0 AND baseline_ctr <= 1",
            name="ck_event_popularity_metrics_baseline_ctr_range",
        ),
        sa.CheckConstraint(
            "smoothed_ctr >= 0 AND smoothed_ctr <= 1",
            name="ck_event_popularity_metrics_smoothed_ctr_range",
        ),
        sa.CheckConstraint(
            "engagement_score >= 0 AND engagement_score <= 1",
            name="ck_event_popularity_metrics_engagement_score_range",
        ),
        sa.UniqueConstraint(
            "event_id",
            "window_start",
            "window_end",
            name="uq_event_popularity_metrics_event_window",
        ),
    )
    op.create_index(
        "ix_event_popularity_metrics_event",
        "event_popularity_metrics",
        ["event_id"],
    )
    op.create_index(
        "ix_event_popularity_metrics_event_window_end",
        "event_popularity_metrics",
        ["event_id", "window_end"],
    )


def downgrade() -> None:
    op.drop_table("event_popularity_metrics")
