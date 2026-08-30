"""add title_inclusion rule group

Revision ID: 20260829_0017
Revises: 20260829_0016
Create Date: 2026-08-30

- Expand the rule_group check constraint on filter_rules with 'title_inclusion'.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0017"
down_revision: str | None = "20260829_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RULE_GROUPS = ("title_exclusion", "domain_blocklist", "title_inclusion")
PREVIOUS_RULE_GROUPS = ("title_exclusion", "domain_blocklist")


def _values(groups: tuple[str, ...]) -> str:
    return ", ".join(f"'{group}'" for group in groups)


def upgrade() -> None:
    op.drop_constraint("filter_rule_group_values", "filter_rules", type_="check")
    op.create_check_constraint(
        "filter_rule_group_values",
        "filter_rules",
        f"rule_group IN ({_values(RULE_GROUPS)})",
    )


def downgrade() -> None:
    # Delete title_inclusion rules first
    op.execute("DELETE FROM filter_rules WHERE rule_group = 'title_inclusion'")
    op.drop_constraint("filter_rule_group_values", "filter_rules", type_="check")
    op.create_check_constraint(
        "filter_rule_group_values",
        "filter_rules",
        f"rule_group IN ({_values(PREVIOUS_RULE_GROUPS)})",
    )
