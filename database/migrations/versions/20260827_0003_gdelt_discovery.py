"""add GDELT discovery provenance

Revision ID: 20260827_0003
Revises: 20260826_0002
Create Date: 2026-08-27

GDELT discovers an article; the publisher wrote it. Recording the two separately
is what keeps a local newspaper from being labelled as its discovery mechanism.
The added timestamps stay distinct because detection lead time is the difference
between them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0003"
down_revision: str | None = "20260826_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DISCOVERY_METHODS = ("direct", "gdelt")


def upgrade() -> None:
    op.create_table(
        "gdelt_query_rules",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("rule_group", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), server_default="any", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_gdelt_query_rules"),
        sa.UniqueConstraint("query", "language", name="uq_gdelt_query_rules_query"),
    )

    op.add_column("sources", sa.Column("domain", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_sources_domain", "sources", ["domain"])

    op.add_column(
        "signals",
        sa.Column(
            "discovered_via",
            sa.Enum(
                *DISCOVERY_METHODS,
                name="discovery_method_values",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="direct",
            nullable=False,
        ),
    )
    # Added nullable, backfilled, then constrained. Adding it NOT NULL outright
    # would fail on any database that already holds signals.
    op.add_column("signals", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE signals SET first_seen_at = retrieved_at WHERE first_seen_at IS NULL")
    op.alter_column("signals", "first_seen_at", nullable=False)

    op.add_column("signals", sa.Column("gdelt_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "signals", sa.Column("published_at_offset_minutes", sa.SmallInteger(), nullable=True)
    )
    op.add_column(
        "signals",
        sa.Column("retrieval_attempts", sa.SmallInteger(), server_default="0", nullable=False),
    )
    op.add_column("signals", sa.Column("query_rule_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_signals_query_rule_id_gdelt_query_rules",
        "signals",
        "gdelt_query_rules",
        ["query_rule_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_signals_discovered_via", "signals", ["discovered_via"])
    op.create_index("ix_signals_first_seen_at", "signals", ["first_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_signals_first_seen_at", table_name="signals")
    op.drop_index("ix_signals_discovered_via", table_name="signals")
    op.drop_constraint("fk_signals_query_rule_id_gdelt_query_rules", "signals", type_="foreignkey")
    op.drop_column("signals", "query_rule_id")
    op.drop_column("signals", "retrieval_attempts")
    op.drop_column("signals", "published_at_offset_minutes")
    op.drop_column("signals", "gdelt_seen_at")
    op.drop_column("signals", "first_seen_at")
    op.drop_constraint("ck_signals_discovery_method_values", "signals", type_="check")
    op.drop_column("signals", "discovered_via")
    op.drop_constraint("uq_sources_domain", "sources", type_="unique")
    op.drop_column("sources", "domain")
    op.drop_table("gdelt_query_rules")
