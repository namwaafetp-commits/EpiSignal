"""story groups

Revision ID: 20260829_0013
Revises: 20260829_0012
Create Date: 2026-08-29

Pre-group storage for the default-off pre-group stage: `story_groups` holds
one row per pre-group with its state, `story_group_members` links signals to
their role. No signal changes: deferral is membership, not a processing
status, so every existing reader of `signals.processing_status` keeps its
meaning whether or not this stage ever runs.

The downgrade drops both tables. Membership is routing that the stage can
recompute from `normalized` signals; nothing it recorded is evidence.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0013"
down_revision: str | None = "20260829_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATE = sa.Enum(
    "open",
    "resolved",
    "expired",
    name="story_group_state_values",
    native_enum=False,
    create_constraint=True,
)
_ROLE = sa.Enum(
    "representative",
    "deferred",
    name="story_group_role_values",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "story_groups",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("rule_group", sa.Text(), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.Column("state", _STATE, nullable=False, server_default="open"),
        sa.Column("window_days", sa.SmallInteger(), nullable=False),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_story_groups_state", "story_groups", ["state"])
    op.create_index("ix_story_groups_window", "story_groups", ["rule_group", "country_code"])
    op.create_table(
        "story_group_members",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "group_id",
            sa.Uuid(),
            sa.ForeignKey("story_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "signal_id",
            sa.Uuid(),
            sa.ForeignKey("signals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", _ROLE, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_id", name="uq_story_group_members_signal"),
    )
    op.create_index("ix_story_group_members_group", "story_group_members", ["group_id"])
    op.create_index("ix_story_group_members_role", "story_group_members", ["role"])


def downgrade() -> None:
    op.drop_table("story_group_members")
    op.drop_table("story_groups")
