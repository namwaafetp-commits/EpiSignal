"""add event summarization fields and a versioned summary history

Revision ID: 20260830_0019
Revises: 20260830_0018
Create Date: 2026-08-30

Events gain the headline/summary/article_count/last_summarized_at the lean MVP
reads, and a new ``event_summaries`` table keeps every generated version so a
re-summary never overwrites what a reader was already shown. The purpose
vocabularies widen by one value for the ambiguous-match judge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0019"
down_revision: str | None = "20260830_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_PURPOSES = (
    "classification",
    "extraction",
    "follow_up",
    "triage",
    "event_summary",
    "event_match_judge",
)
PREVIOUS_AI_PURPOSES = AI_PURPOSES[:5]


def _values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.add_column("events", sa.Column("headline", sa.Text(), nullable=True))
    op.add_column("events", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "events",
        sa.Column("article_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "events", sa.Column("last_summarized_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_events_last_summarized_at", "events", ["last_summarized_at"])

    op.create_table(
        "event_summaries",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "monitoring",
                "ongoing",
                "expanding",
                "stable",
                "declining",
                "resolved",
                "unknown",
                native_enum=False,
                create_constraint=True,
                name="event_status_values",
            ),
            nullable=False,
        ),
        sa.Column("latest_development", sa.Text(), nullable=True),
        sa.Column("uncertainties", postgresql.JSONB(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("source_signal_ids", postgresql.JSONB(), nullable=True),
        sa.Column("counts", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("event_id", "version", name="uq_event_summaries_event_version"),
    )
    op.create_index("ix_event_summaries_event", "event_summaries", ["event_id"])

    op.drop_constraint("ai_purpose_values", "ai_requests", type_="check")
    op.create_check_constraint(
        "ai_purpose_values",
        "ai_requests",
        f"purpose IN ({_values(AI_PURPOSES)})",
    )
    op.drop_constraint("ai_model_purpose_values", "ai_models", type_="check")
    op.create_check_constraint(
        "ai_model_purpose_values",
        "ai_models",
        f"purpose IN ({_values(AI_PURPOSES)})",
    )


def downgrade() -> None:
    if not op.get_context().as_sql:
        conn = op.get_bind()
        judge_requests = conn.execute(
            sa.text("SELECT count(*) AS n FROM ai_requests WHERE purpose = 'event_match_judge'")
        ).scalar_one()
        if judge_requests > 0:
            raise RuntimeError(
                "Cannot downgrade the purpose vocabulary while event_match_judge requests exist"
            )

    op.drop_constraint("ai_model_purpose_values", "ai_models", type_="check")
    op.create_check_constraint(
        "ai_model_purpose_values",
        "ai_models",
        f"purpose IN ({_values(PREVIOUS_AI_PURPOSES)})",
    )
    op.drop_constraint("ai_purpose_values", "ai_requests", type_="check")
    op.create_check_constraint(
        "ai_purpose_values",
        "ai_requests",
        f"purpose IN ({_values(PREVIOUS_AI_PURPOSES)})",
    )

    op.drop_index("ix_event_summaries_event", table_name="event_summaries")
    op.drop_table("event_summaries")

    op.drop_index("ix_events_last_summarized_at", table_name="events")
    op.drop_column("events", "last_summarized_at")
    op.drop_column("events", "article_count")
    op.drop_column("events", "summary")
    op.drop_column("events", "headline")
