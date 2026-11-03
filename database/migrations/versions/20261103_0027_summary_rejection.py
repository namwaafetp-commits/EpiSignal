"""Store the most recent rejected summary request fingerprint."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0027"
down_revision: str | None = "20260917_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("summary_rejected_at", sa.DateTime(timezone=True)))
    op.add_column("events", sa.Column("summary_rejected_fingerprint", sa.String(64)))


def downgrade() -> None:
    op.drop_column("events", "summary_rejected_fingerprint")
    op.drop_column("events", "summary_rejected_at")
