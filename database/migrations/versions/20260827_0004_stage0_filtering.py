"""add Stage 0 filtering and deduplication

Revision ID: 20260827_0004
Revises: 20260827_0003
Create Date: 2026-08-27

A rejected sighting is not a signal: it was never retrieved and has no body, so
it gets its own table rather than a row with an invented retrieval time. A
syndicated copy is a signal, keeps its publisher, and points at the copy seen
first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0004"
down_revision: str | None = "20260827_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FILTER_RULE_GROUPS = ("title_exclusion", "domain_blocklist")

PROCESSING_STATUSES = (
    "fetched",
    "normalized",
    "classified",
    "extracted",
    "geocoded",
    "matched",
    "published",
    "duplicate",
    "failed",
    "needs_review",
)

PREVIOUS_PROCESSING_STATUSES = tuple(
    status for status in PROCESSING_STATUSES if status != "duplicate"
)


def _values(statuses: tuple[str, ...]) -> str:
    return ", ".join(f"'{status}'" for status in statuses)


def upgrade() -> None:
    op.create_table(
        "filter_rules",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "rule_group",
            sa.Enum(
                *FILTER_RULE_GROUPS,
                name="filter_rule_group_values",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_filter_rules"),
        sa.UniqueConstraint("rule_group", "pattern", name="uq_filter_rules_rule_group"),
    )

    op.create_table(
        "rejected_sightings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("gdelt_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filter_rule_id", sa.Uuid(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_rejected_sightings"),
        sa.UniqueConstraint("canonical_url", name="uq_rejected_sightings_canonical_url"),
        sa.ForeignKeyConstraint(
            ["filter_rule_id"],
            ["filter_rules.id"],
            name="fk_rejected_sightings_filter_rule_id_filter_rules",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_rejected_sightings_filter_rule_id", "rejected_sightings", ["filter_rule_id"]
    )
    op.create_index("ix_rejected_sightings_rejected_at", "rejected_sightings", ["rejected_at"])

    op.add_column("signals", sa.Column("duplicate_of_signal_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_signals_duplicate_of_signal_id_signals",
        "signals",
        "signals",
        ["duplicate_of_signal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_signals_duplicate_of_signal_id", "signals", ["duplicate_of_signal_id"])

    # The vocabulary is a check constraint over values, not a native enum, so
    # widening it means replacing the constraint.
    op.drop_constraint("processing_status_values", "signals", type_="check")
    op.create_check_constraint(
        "processing_status_values",
        "signals",
        f"processing_status IN ({_values(PROCESSING_STATUSES)})",
    )


def downgrade() -> None:
    # Nothing may be left in the value about to disappear.
    op.execute(
        "UPDATE signals SET processing_status = 'fetched' WHERE processing_status = 'duplicate'"
    )

    op.drop_constraint("processing_status_values", "signals", type_="check")
    op.create_check_constraint(
        "processing_status_values",
        "signals",
        f"processing_status IN ({_values(PREVIOUS_PROCESSING_STATUSES)})",
    )

    op.drop_index("ix_signals_duplicate_of_signal_id", table_name="signals")
    op.drop_constraint("fk_signals_duplicate_of_signal_id_signals", "signals", type_="foreignkey")
    op.drop_column("signals", "duplicate_of_signal_id")

    op.drop_index("ix_rejected_sightings_rejected_at", table_name="rejected_sightings")
    op.drop_index("ix_rejected_sightings_filter_rule_id", table_name="rejected_sightings")
    op.drop_table("rejected_sightings")
    # No explicit constraint drop: the check constraint lives on the table and
    # goes with it.
    op.drop_table("filter_rules")
