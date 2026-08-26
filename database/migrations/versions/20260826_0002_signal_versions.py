"""version signals by content hash

Revision ID: 20260826_0002
Revises: 20260826_0001
Create Date: 2026-08-26

A revised source document keeps its URL, so URL alone cannot identify a signal.
Identity becomes the pair of URL and content hash, which lets a revision be
stored as an additional row instead of overwriting the text an earlier
observation was extracted from.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260826_0002"
down_revision: str | None = "20260826_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_signals_url", "signals", type_="unique")
    op.create_unique_constraint("uq_signals_url_content_hash", "signals", ["url", "content_hash"])


def downgrade() -> None:
    # This fails when several versions of one URL exist, which is correct:
    # discarding stored evidence to satisfy a narrower constraint would be worse
    # than a failed downgrade.
    op.drop_constraint("uq_signals_url_content_hash", "signals", type_="unique")
    op.create_unique_constraint("uq_signals_url", "signals", ["url"])
