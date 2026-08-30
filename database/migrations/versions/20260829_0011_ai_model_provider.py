"""ai model provider

Revision ID: 20260829_0011
Revises: 20260829_0010
Create Date: 2026-08-29

Adds `ai_models.provider` with a closed vocabulary (`openrouter`, `gemini`)
and backfills every existing row to `openrouter`, which is a fact about
history: every roster row to date was served through the OpenRouter adapter.
The column keeps the ladder one ladder — the rung's provider names the adapter,
and tier climbing crosses providers without any fallback code.

The downgrade drops the column. It does not attempt to restore provider
knowledge that only ever existed here, because a rolled-back roster is
uniformly OpenRouter again by definition.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0011"
down_revision: str | None = "20260829_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVIDER = sa.Enum(
    "openrouter",
    "gemini",
    name="ai_provider_values",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda members: members,
)


def upgrade() -> None:
    op.add_column(
        "ai_models",
        sa.Column(
            "provider",
            _PROVIDER,
            nullable=False,
            server_default="openrouter",
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_models", "provider")
