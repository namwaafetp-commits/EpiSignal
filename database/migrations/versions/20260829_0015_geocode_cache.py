"""geocode cache

Revision ID: 20260829_0015
Revises: 20260829_0014
Create Date: 2026-08-29

A persistent cache for place names the local gazetteer has no candidate for:
- Create geocode_cache, keyed on (normalized_query, country_code) with a NULL
  country_code recording a worldwide lookup.
- Index country_code so scope-scoped pruning does not scan the table.
- Downgrade drops the table; cache rows are refetchable by definition, so the
  drop loses nothing that cannot be rebuilt.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0015"
down_revision: str | None = "20260829_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "geocode_cache",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("normalized_query", sa.Text(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("resolved_name", sa.Text(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("source", sa.Text(), server_default="nominatim", nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_geocode_cache"),
        sa.UniqueConstraint(
            "normalized_query", "country_code", name="uq_geocode_cache_normalized_query"
        ),
        sa.CheckConstraint(
            "latitude >= -90 AND latitude <= 90", name="ck_geocode_cache_latitude_range"
        ),
        sa.CheckConstraint(
            "longitude >= -180 AND longitude <= 180", name="ck_geocode_cache_longitude_range"
        ),
    )
    op.create_index("ix_geocode_cache_country_code", "geocode_cache", ["country_code"])


def downgrade() -> None:
    op.drop_index("ix_geocode_cache_country_code", table_name="geocode_cache")
    op.drop_table("geocode_cache")
