"""add structured EpiSignal event flash-brief fields

Revision ID: 20260901_0020
Revises: 20260830_0019
Create Date: 2026-09-01

The previous versioned summary rows remain readable. New rows add the
controlled trajectory and four structured flash-brief sections while retaining
the rendered summary text for the existing denormalized event surface.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260901_0020"
down_revision: str | None = "20260830_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "event_observations", sa.Column("material_facts", postgresql.JSONB(), nullable=True)
    )
    op.add_column("event_summaries", sa.Column("trajectory", sa.Text(), nullable=True))
    op.add_column("event_summaries", sa.Column("snapshot", postgresql.JSONB(), nullable=True))
    op.add_column("event_summaries", sa.Column("key_driver", sa.Text(), nullable=True))
    op.add_column("event_summaries", sa.Column("response", sa.Text(), nullable=True))
    op.add_column("event_summaries", sa.Column("risk", sa.Text(), nullable=True))
    op.create_check_constraint(
        "event_summary_trajectory_values",
        "event_summaries",
        "trajectory IS NULL OR trajectory IN ("
        "'Emerging', 'Increasing', 'Stable', 'Declining', "
        "'Contained', 'Resolved', 'Unclear')",
    )


def downgrade() -> None:
    op.drop_constraint("event_summary_trajectory_values", "event_summaries", type_="check")
    op.drop_column("event_summaries", "risk")
    op.drop_column("event_summaries", "response")
    op.drop_column("event_summaries", "key_driver")
    op.drop_column("event_summaries", "snapshot")
    op.drop_column("event_summaries", "trajectory")
    op.drop_column("event_observations", "material_facts")
