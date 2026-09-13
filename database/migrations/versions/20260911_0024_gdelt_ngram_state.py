"""add durable GDELT NGram discovery cursor

The NGram batch watermark is provider state, not scheduler window state. A
separate one-row table lets a failed batch remain retryable and keeps Telegram
SQLite state unrelated to surveillance discovery.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260911_0024"
down_revision: str | None = "20260908_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gdelt_discovery_state",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("cursor_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("provider", name="pk_gdelt_discovery_state"),
    )


def downgrade() -> None:
    op.drop_table("gdelt_discovery_state")
