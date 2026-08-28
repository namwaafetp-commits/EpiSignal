"""rename event score columns and adjust check constraints

Revision ID: 20260828_0007
Revises: 20260827_0006
Create Date: 2026-08-28

Renames `events.attention_score` to `early_signal_score` and
`events.confidence_score` to `evidence_score`, adjusting both check constraints
to the 0–1 range. The table is empty at the time of migration, making this
lossless in both directions.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260828_0007"
down_revision: str | None = "20260827_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("attention_score_range", "events", type_="check")
    op.drop_constraint("confidence_score_range", "events", type_="check")

    op.alter_column("events", "attention_score", new_column_name="early_signal_score")
    op.alter_column("events", "confidence_score", new_column_name="evidence_score")

    op.create_check_constraint(
        "early_signal_score_range",
        "events",
        "early_signal_score >= 0 AND early_signal_score <= 1",
    )
    op.create_check_constraint(
        "evidence_score_range",
        "events",
        "evidence_score >= 0 AND evidence_score <= 1",
    )


def downgrade() -> None:
    op.drop_constraint("early_signal_score_range", "events", type_="check")
    op.drop_constraint("evidence_score_range", "events", type_="check")

    op.alter_column("events", "early_signal_score", new_column_name="attention_score")
    op.alter_column("events", "evidence_score", new_column_name="confidence_score")

    op.create_check_constraint(
        "attention_score_range",
        "events",
        "attention_score >= 0 AND attention_score <= 100",
    )
    op.create_check_constraint(
        "confidence_score_range",
        "events",
        "confidence_score >= 0 AND confidence_score <= 1",
    )
