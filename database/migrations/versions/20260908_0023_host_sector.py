"""add signal host-sector classification

Revision ID: 20260908_0023
Revises: 20260904_0022
Create Date: 2026-09-08

The value is nullable for historical signals. Readers treat null as unknown;
no historical model backfill is performed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260908_0023"
down_revision: str | None = "20260904_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


HOST_SECTOR = sa.Enum(
    "human",
    "animal",
    "both",
    "unknown",
    name="host_sector_values",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.add_column("signals", sa.Column("host_sector", HOST_SECTOR, nullable=True))
    op.create_index("ix_signals_host_sector", "signals", ["host_sector"])
    op.add_column("events", sa.Column("summary_payload", postgresql.JSONB(), nullable=True))
    op.add_column(
        "event_summaries", sa.Column("summary_payload", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("event_summaries", "summary_payload")
    op.drop_column("events", "summary_payload")
    op.drop_index("ix_signals_host_sector", table_name="signals")
    op.drop_column("signals", "host_sector")
