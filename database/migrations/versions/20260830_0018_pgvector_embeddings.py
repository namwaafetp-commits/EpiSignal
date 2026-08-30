"""enable pgvector and store signal embeddings

Revision ID: 20260830_0018
Revises: 20260830_0017
Create Date: 2026-08-30

The extension survives downgrade because another table may come to depend on
it. Removing this revision removes only the column and index it owns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260830_0018"
down_revision: str | None = "20260830_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("signals", sa.Column("embedding", Vector(1024), nullable=True))
    # HNSW grows incrementally with this append-heavy table. IVFFlat would need
    # rebuilding as the corpus changes, so it is the wrong default here.
    op.execute(
        "CREATE INDEX ix_signals_embedding ON signals USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_signals_embedding", table_name="signals")
    op.drop_column("signals", "embedding")
