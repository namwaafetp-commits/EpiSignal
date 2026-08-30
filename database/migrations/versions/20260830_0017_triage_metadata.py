"""add early triage metadata and purpose-scoped model rosters

Revision ID: 20260830_0017
Revises: 20260829_0017
Create Date: 2026-08-30

The Python ``normalize_title`` function is authoritative. The SQL backfill is
a convenience for existing rows; it can be re-derived by running triage again.
PostgreSQL has no built-in NFKC normalization, so new writes always use the
Python function before relying on equality.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0017"
down_revision: str | None = "20260829_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_PURPOSES = (
    "classification",
    "extraction",
    "follow_up",
    "triage",
    "event_summary",
)
PREVIOUS_AI_PURPOSES = AI_PURPOSES[:3]
TRIAGE_STATUSES = ("pending", "done", "failed")


def _values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.drop_constraint("ai_purpose_values", "ai_requests", type_="check")
    op.create_check_constraint(
        "ai_purpose_values",
        "ai_requests",
        f"purpose IN ({_values(AI_PURPOSES)})",
    )

    op.add_column("signals", sa.Column("normalized_title", sa.Text(), nullable=True))
    op.add_column(
        "signals",
        sa.Column(
            "triage_status",
            sa.Enum(
                *TRIAGE_STATUSES,
                name="triage_status_values",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="pending",
            nullable=False,
        ),
    )
    op.add_column("signals", sa.Column("triage_category", sa.Text(), nullable=True))
    op.add_column("signals", sa.Column("triage_disease_text", sa.Text(), nullable=True))
    op.add_column("signals", sa.Column("triage_country_code", sa.String(length=2), nullable=True))
    op.add_column("signals", sa.Column("triage_admin1", sa.Text(), nullable=True))
    op.add_column("signals", sa.Column("triage_admin2", sa.Text(), nullable=True))
    op.add_column("signals", sa.Column("triage_location_text", sa.Text(), nullable=True))
    op.add_column("signals", sa.Column("triage_confidence", sa.Float(), nullable=True))

    op.add_column(
        "ai_models",
        sa.Column(
            "purpose",
            sa.Enum(
                *AI_PURPOSES,
                name="ai_model_purpose_values",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
    )

    op.create_index("ix_signals_normalized_title", "signals", ["normalized_title"])
    op.create_index(
        "ix_signals_triage_block",
        "signals",
        ["triage_disease_text", "triage_country_code"],
    )

    op.execute(
        r"""
        UPDATE signals
        SET normalized_title = lower(
            btrim(
                regexp_replace(
                    regexp_replace(
                        regexp_replace(
                            title,
                            '\s[-|–—]\s([^-|–—]{1,40})$',
                            '',
                            'g'
                        ),
                        '[^\w\s-]',
                        '',
                        'g'
                    ),
                    '\s+',
                    ' ',
                    'g'
                )
            )
        )
        """
    )


def downgrade() -> None:
    if not op.get_context().as_sql:
        conn = op.get_bind()
        incompatible = (
            conn.execute(
                sa.text(
                    """
                SELECT
                  (SELECT count(*) FROM ai_requests
                   WHERE purpose IN ('triage', 'event_summary')) AS requests,
                  (SELECT count(*) FROM ai_models
                   WHERE purpose IS NOT NULL) AS purposed_models
                """
                )
            )
            .mappings()
            .one()
        )
        if incompatible["requests"] > 0 or incompatible["purposed_models"] > 0:
            raise RuntimeError(
                "Cannot downgrade triage metadata after purpose-scoped AI data exists"
            )

    op.drop_index("ix_signals_triage_block", table_name="signals")
    op.drop_index("ix_signals_normalized_title", table_name="signals")

    op.drop_column("ai_models", "purpose")

    op.drop_column("signals", "triage_confidence")
    op.drop_column("signals", "triage_location_text")
    op.drop_column("signals", "triage_admin2")
    op.drop_column("signals", "triage_admin1")
    op.drop_column("signals", "triage_country_code")
    op.drop_column("signals", "triage_disease_text")
    op.drop_column("signals", "triage_category")
    op.drop_column("signals", "triage_status")
    op.drop_column("signals", "normalized_title")

    op.drop_constraint("ai_purpose_values", "ai_requests", type_="check")
    op.create_check_constraint(
        "ai_purpose_values",
        "ai_requests",
        f"purpose IN ({_values(PREVIOUS_AI_PURPOSES)})",
    )
