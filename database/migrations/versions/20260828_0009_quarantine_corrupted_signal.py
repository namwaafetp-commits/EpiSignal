"""quarantine corrupted signal 852aa204

Revision ID: 20260828_0009
Revises: 20260828_0008
Create Date: 2026-08-28

Quarantines signal 852aa204-846d-4aa6-a256-82c187fdeaef by setting its
processing_status to 'needs_review'. The signal has a title/body mismatch
arising from an early development test fixture where mock cholera text was
written into a Pennsylvania measles record without updating content_hash.

Preserves all fields (title, raw_text, content_hash, ai_extraction) unmutated
for auditability and diagnostic evidence.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0009"
down_revision: str | None = "20260828_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CORRUPTED_SIGNAL_ID = "852aa204-846d-4aa6-a256-82c187fdeaef"


def upgrade() -> None:
    # Quarantine the mismatched signal so it is flagged for review and never
    # treated as a valid extracted signal, while preserving all original text
    # and hashes for forensic traceability.
    op.execute(
        sa.text(
            f"""
            UPDATE signals
            SET processing_status = 'needs_review'
            WHERE id = '{CORRUPTED_SIGNAL_ID}'
              AND processing_status = 'extracted'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE signals
            SET processing_status = 'extracted'
            WHERE id = '{CORRUPTED_SIGNAL_ID}'
              AND processing_status = 'needs_review'
            """
        )
    )
