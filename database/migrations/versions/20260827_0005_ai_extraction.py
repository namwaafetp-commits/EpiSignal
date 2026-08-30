"""add the AI model roster, the request ledger, and the signal disease link

Revision ID: 20260827_0005
Revises: 20260827_0004
Create Date: 2026-08-27

`ai_requests` is a ledger of numbers nobody can recompute after the fact:
tokens, latency, and the price in force at the time. Dropping it is destructive
in a way that dropping a derived table is not, so `downgrade` refuses while it
holds rows unless the operator says otherwise.

`signals.disease_id` is a real foreign key rather than an id inside
`ai_extraction`, because a reference buried in JSONB is one the database cannot
enforce and a deleted disease would leave it dangling in silence.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0005"
down_revision: str | None = "20260827_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_PURPOSES = ("classification", "extraction")
AI_OUTCOMES = ("accepted", "rejected", "unavailable")
PRICE = sa.Numeric(12, 6)
AUDIT_LOSS_VARIABLE = "EPISIGNAL_ALLOW_AI_AUDIT_LOSS"


def upgrade() -> None:
    op.create_table(
        "ai_models",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tier", sa.SmallInteger(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("prompt_price_per_million", PRICE, server_default="0", nullable=False),
        sa.Column("completion_price_per_million", PRICE, server_default="0", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_models"),
        sa.UniqueConstraint("model_id", name="uq_ai_models_model_id"),
        sa.CheckConstraint("tier >= 1 AND tier <= 3", name="ck_ai_models_tier_range"),
    )
    op.create_index("ix_ai_models_tier", "ai_models", ["tier"])

    op.create_table(
        "ai_requests",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("ai_model_id", sa.Uuid(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("tier", sa.SmallInteger(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                *AI_PURPOSES,
                name="ai_purpose_values",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("signal_id", sa.Uuid(), nullable=True),
        sa.Column("batch_size", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("http_status", sa.SmallInteger(), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                *AI_OUTCOMES,
                name="ai_outcome_values",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("prompt_price_per_million", PRICE, nullable=False),
        sa.Column("completion_price_per_million", PRICE, nullable=False),
        sa.Column("cost_usd", PRICE, server_default="0", nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_requests"),
        sa.ForeignKeyConstraint(
            ["ai_model_id"],
            ["ai_models.id"],
            name="fk_ai_requests_ai_model_id_ai_models",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name="fk_ai_requests_signal_id_signals",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_ai_requests_requested_at", "ai_requests", ["requested_at"])
    op.create_index("ix_ai_requests_signal_id", "ai_requests", ["signal_id"])
    op.create_index("ix_ai_requests_outcome", "ai_requests", ["outcome"])

    op.add_column("signals", sa.Column("disease_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_signals_disease_id_diseases",
        "signals",
        "diseases",
        ["disease_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_signals_disease_id", "signals", ["disease_id"])


def downgrade() -> None:
    # The ledger is the only record of what inference cost. It cannot be
    # rebuilt from anything else in the database, so discarding it is a
    # separately authorized act rather than a side effect of rolling back.
    #
    # Skipped while rendering offline SQL: there is no connection to count with,
    # and nothing is destroyed by printing a statement for a human to read.
    if not op.get_context().as_sql:
        connection = op.get_bind()
        rows = connection.execute(sa.text("SELECT count(*) FROM ai_requests")).scalar_one()
        if rows and os.environ.get(AUDIT_LOSS_VARIABLE) != "1":
            raise RuntimeError(
                f"ai_requests holds {rows} cost rows that no other table can reproduce. "
                f"Export them first, then set {AUDIT_LOSS_VARIABLE}=1 to confirm the loss."
            )

    op.drop_index("ix_signals_disease_id", table_name="signals")
    op.drop_constraint("fk_signals_disease_id_diseases", "signals", type_="foreignkey")
    op.drop_column("signals", "disease_id")

    op.drop_index("ix_ai_requests_outcome", table_name="ai_requests")
    op.drop_index("ix_ai_requests_signal_id", table_name="ai_requests")
    op.drop_index("ix_ai_requests_requested_at", table_name="ai_requests")
    op.drop_table("ai_requests")

    op.drop_index("ix_ai_models_tier", table_name="ai_models")
    # No explicit constraint drop: the check constraint lives on the table and
    # goes with it.
    op.drop_table("ai_models")
