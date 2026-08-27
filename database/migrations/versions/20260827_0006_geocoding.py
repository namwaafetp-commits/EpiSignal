"""add the gazetteer and the resolved locations of signals

Revision ID: 20260827_0006
Revises: 20260827_0005
Create Date: 2026-08-27

`gazetteer_places` is reference data: everything in it comes from a committed
seed artifact, so dropping it loses nothing that reseeding cannot rebuild.
`signal_locations` is derived from signal extractions and the gazetteer,
so it is rebuildable too. Neither needs the ledger protection
`20260827_0005` gives `ai_requests`.

The extraction column on `signals` is not touched. It records what the model
said, and this migration adds a place to record what the gazetteer answered.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography

revision: str = "20260827_0006"
down_revision: str | None = "20260827_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRECISIONS = ("place", "admin2", "admin1", "country", "unresolved")
LOCATION_ROLES = ("primary", "exposure", "diagnosis", "travel", "reporting", "affected_area")


def _point() -> Geography:
    return Geography(geometry_type="POINT", srid=4326, spatial_index=False)


def _precision(name: str) -> sa.Enum:
    return sa.Enum(*PRECISIONS, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.create_table(
        "gazetteer_places",
        sa.Column("geonames_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("ascii_name", sa.Text(), nullable=False),
        sa.Column(
            "alternate_names",
            sa.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("feature_code", sa.String(length=10), nullable=False),
        sa.Column("precision", _precision("precision_values"), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("admin1_code", sa.String(length=20), nullable=True),
        sa.Column("admin2_code", sa.String(length=80), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("geometry", _point(), nullable=True),
        sa.Column("population", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("geonames_id", name="pk_gazetteer_places"),
        sa.CheckConstraint(
            "latitude >= -90 AND latitude <= 90", name="ck_gazetteer_places_latitude_range"
        ),
        sa.CheckConstraint(
            "longitude >= -180 AND longitude <= 180", name="ck_gazetteer_places_longitude_range"
        ),
    )
    op.create_index("ix_gazetteer_places_normalized_name", "gazetteer_places", ["normalized_name"])
    op.create_index("ix_gazetteer_places_ascii_name", "gazetteer_places", ["ascii_name"])
    op.create_index("ix_gazetteer_places_precision", "gazetteer_places", ["precision"])
    op.create_index(
        "ix_gazetteer_places_scope",
        "gazetteer_places",
        ["country_code", "admin1_code", "normalized_name"],
    )
    op.create_index(
        "ix_gazetteer_places_alternate_names",
        "gazetteer_places",
        ["alternate_names"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_gazetteer_places_geometry",
        "gazetteer_places",
        ["geometry"],
        postgresql_using="gist",
    )

    op.create_table(
        "signal_locations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=False),
        sa.Column(
            "location_role",
            sa.Enum(
                *LOCATION_ROLES,
                name="location_role_values",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("country_name", sa.Text(), nullable=True),
        sa.Column("admin1_name", sa.Text(), nullable=True),
        sa.Column("place_name", sa.Text(), nullable=True),
        sa.Column("precision", _precision("precision_values"), nullable=False),
        sa.Column("geonames_id", sa.Integer(), nullable=True),
        sa.Column("resolved_name", sa.Text(), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("admin1", sa.Text(), nullable=True),
        sa.Column("admin2", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("geometry", _point(), nullable=True),
        sa.Column("geocoding_source", sa.Text(), nullable=True),
        sa.Column("geocoding_confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_signal_locations"),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name="fk_signal_locations_signal_id_signals",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "latitude >= -90 AND latitude <= 90", name="ck_signal_locations_latitude_range"
        ),
        sa.CheckConstraint(
            "longitude >= -180 AND longitude <= 180", name="ck_signal_locations_longitude_range"
        ),
        sa.CheckConstraint(
            "geocoding_confidence >= 0 AND geocoding_confidence <= 1",
            name="ck_signal_locations_geocoding_confidence_range",
        ),
    )
    op.create_index("ix_signal_locations_signal_id", "signal_locations", ["signal_id"])
    op.create_index("ix_signal_locations_precision", "signal_locations", ["precision"])
    op.create_index("ix_signal_locations_country_code", "signal_locations", ["country_code"])
    op.create_index(
        "ix_signal_locations_geocoding_source", "signal_locations", ["geocoding_source"]
    )
    op.create_index(
        "ix_signal_locations_geometry",
        "signal_locations",
        ["geometry"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_index("ix_signal_locations_geometry", table_name="signal_locations")
    op.drop_index("ix_signal_locations_geocoding_source", table_name="signal_locations")
    op.drop_index("ix_signal_locations_country_code", table_name="signal_locations")
    op.drop_index("ix_signal_locations_precision", table_name="signal_locations")
    op.drop_index("ix_signal_locations_signal_id", table_name="signal_locations")
    op.drop_table("signal_locations")

    op.drop_index("ix_gazetteer_places_geometry", table_name="gazetteer_places")
    op.drop_index("ix_gazetteer_places_alternate_names", table_name="gazetteer_places")
    op.drop_index("ix_gazetteer_places_scope", table_name="gazetteer_places")
    op.drop_index("ix_gazetteer_places_precision", table_name="gazetteer_places")
    op.drop_index("ix_gazetteer_places_ascii_name", table_name="gazetteer_places")
    op.drop_index("ix_gazetteer_places_normalized_name", table_name="gazetteer_places")
    op.drop_table("gazetteer_places")
