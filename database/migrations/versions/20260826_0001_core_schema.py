"""create core epidemiology schema

Revision ID: 20260826_0001
Revises:
Create Date: 2026-08-26

Vocabularies are written out literally rather than imported from the application
so that this revision keeps describing the schema it originally created even as
the Python enumerations evolve.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

revision: str = "20260826_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SOURCE_TYPE = sa.Enum(
    "international_organization",
    "regional_public_health_agency",
    "national_public_health_agency",
    "ministry_of_health",
    "scientific",
    "humanitarian",
    "major_media",
    "local_media",
    "other",
    native_enum=False,
    create_constraint=True,
    name="source_type_values",
)
CREDIBILITY_TIER = sa.Enum(
    "official",
    "high",
    "medium",
    "unknown",
    native_enum=False,
    create_constraint=True,
    name="credibility_tier_values",
)
SIGNAL_TYPE = sa.Enum(
    "outbreak_report",
    "surveillance_update",
    "case_report",
    "imported_case",
    "public_health_action",
    "vaccination_campaign",
    "risk_assessment",
    "situation_report",
    "research",
    "rumor",
    "unknown",
    native_enum=False,
    create_constraint=True,
    name="signal_type_values",
)
PROCESSING_STATUS = sa.Enum(
    "fetched",
    "normalized",
    "classified",
    "extracted",
    "geocoded",
    "matched",
    "published",
    "failed",
    "needs_review",
    native_enum=False,
    create_constraint=True,
    name="processing_status_values",
)
EVENT_TYPE = sa.Enum(
    "outbreak",
    "cluster",
    "single_case",
    "imported_case",
    "seasonal_surveillance",
    "zoonotic_event",
    "foodborne_outbreak",
    "healthcare_associated_outbreak",
    "unknown_disease_event",
    "other",
    native_enum=False,
    create_constraint=True,
    name="event_type_values",
)
EVENT_STATUS = sa.Enum(
    "monitoring",
    "ongoing",
    "expanding",
    "stable",
    "declining",
    "resolved",
    "unknown",
    native_enum=False,
    create_constraint=True,
    name="event_status_values",
)
VERIFICATION_STATUS = sa.Enum(
    "officially_confirmed",
    "high_credibility",
    "signal",
    "unverified",
    "rumor_monitoring",
    native_enum=False,
    create_constraint=True,
    name="verification_status_values",
)
RELATIONSHIP_TYPE = sa.Enum(
    "initial_report",
    "update",
    "supporting_source",
    "risk_assessment",
    "public_health_response",
    "correction",
    "background",
    native_enum=False,
    create_constraint=True,
    name="relationship_type_values",
)
LOCATION_ROLE = sa.Enum(
    "primary",
    "exposure",
    "diagnosis",
    "travel",
    "reporting",
    "affected_area",
    native_enum=False,
    create_constraint=True,
    name="location_role_values",
)

POINT = Geography(geometry_type="POINT", srid=4326, spatial_index=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("source_type", SOURCE_TYPE, nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("feed_url", sa.Text(), nullable=True),
        sa.Column("credibility_tier", CREDIBILITY_TIER, nullable=False),
        sa.Column("is_official", sa.Boolean(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
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
        sa.CheckConstraint("length(country_code) = 2", name="country_code_alpha2"),
        sa.PrimaryKeyConstraint("id", name="pk_sources"),
        sa.UniqueConstraint("name", name="uq_sources_name"),
        sa.UniqueConstraint("base_url", name="uq_sources_base_url"),
        sa.UniqueConstraint("feed_url", name="uq_sources_feed_url"),
    )

    op.create_table(
        "diseases",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("icd10", sa.String(length=16), nullable=True),
        sa.Column(
            "synonyms",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("category", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_diseases"),
        sa.UniqueConstraint("slug", name="uq_diseases_slug"),
    )

    op.create_table(
        "pathogens",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("taxonomy", sa.Text(), nullable=True),
        sa.Column(
            "synonyms",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
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
        sa.PrimaryKeyConstraint("id", name="pk_pathogens"),
        sa.UniqueConstraint("slug", name="uq_pathogens_slug"),
    )

    op.create_table(
        "signals",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("public_health_relevant", sa.Boolean(), nullable=True),
        sa.Column("signal_type", SIGNAL_TYPE, nullable=False),
        sa.Column("ai_extraction", postgresql.JSONB(), nullable=True),
        sa.Column("ai_model", sa.Text(), nullable=True),
        sa.Column("ai_processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_status", PROCESSING_STATUS, nullable=False),
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
        sa.CheckConstraint(
            "relevance_score >= 0 AND relevance_score <= 1",
            name="relevance_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_signals_source_id_sources",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_signals"),
        sa.UniqueConstraint("url", name="uq_signals_url"),
    )
    op.create_index("ix_signals_source_id", "signals", ["source_id"])
    op.create_index("ix_signals_published_at", "signals", ["published_at"])
    op.create_index("ix_signals_canonical_url", "signals", ["canonical_url"])
    op.create_index("ix_signals_content_hash", "signals", ["content_hash"])
    op.create_index("ix_signals_processing_status", "signals", ["processing_status"])

    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("public_id", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("disease_id", sa.Uuid(), nullable=True),
        sa.Column("pathogen_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", EVENT_TYPE, nullable=False),
        sa.Column("status", EVENT_STATUS, nullable=False),
        sa.Column("verification_status", VERIFICATION_STATUS, nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("admin1", sa.Text(), nullable=True),
        sa.Column("admin2", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("geometry", POINT, nullable=True),
        sa.Column("first_signal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_start_date", sa.Date(), nullable=True),
        sa.Column(
            "last_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attention_score", sa.Float(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
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
        sa.CheckConstraint("latitude >= -90 AND latitude <= 90", name="latitude_range"),
        sa.CheckConstraint("longitude >= -180 AND longitude <= 180", name="longitude_range"),
        sa.CheckConstraint(
            "attention_score >= 0 AND attention_score <= 100",
            name="attention_score_range",
        ),
        sa.CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="confidence_score_range",
        ),
        sa.ForeignKeyConstraint(
            ["disease_id"],
            ["diseases.id"],
            name="fk_events_disease_id_diseases",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pathogen_id"],
            ["pathogens.id"],
            name="fk_events_pathogen_id_pathogens",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
        sa.UniqueConstraint("public_id", name="uq_events_public_id"),
        sa.UniqueConstraint("slug", name="uq_events_slug"),
    )
    op.create_index("ix_events_status", "events", ["status"])
    op.create_index("ix_events_verification_status", "events", ["verification_status"])
    op.create_index("ix_events_disease_id", "events", ["disease_id"])
    op.create_index("ix_events_country_code", "events", ["country_code"])
    op.create_index("ix_events_last_updated_at", "events", ["last_updated_at"])
    op.create_index("ix_events_geometry", "events", ["geometry"], postgresql_using="gist")

    op.create_table(
        "event_signals",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=False),
        sa.Column("relationship_type", RELATIONSHIP_TYPE, nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("match_score >= 0 AND match_score <= 1", name="match_score_range"),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name="fk_event_signals_event_id_events",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name="fk_event_signals_signal_id_signals",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", "signal_id", name="pk_event_signals"),
    )

    op.create_table(
        "event_observations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("signal_id", sa.Uuid(), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspected_cases", sa.Integer(), nullable=True),
        sa.Column("probable_cases", sa.Integer(), nullable=True),
        sa.Column("confirmed_cases", sa.Integer(), nullable=True),
        sa.Column("total_cases", sa.Integer(), nullable=True),
        sa.Column("new_cases", sa.Integer(), nullable=True),
        sa.Column("deaths", sa.Integer(), nullable=True),
        sa.Column("new_deaths", sa.Integer(), nullable=True),
        sa.Column("recoveries", sa.Integer(), nullable=True),
        sa.Column("hospitalizations", sa.Integer(), nullable=True),
        sa.Column("cfr", sa.Float(), nullable=True),
        sa.Column("affected_admin_areas", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("suspected_cases >= 0", name="suspected_cases_non_negative"),
        sa.CheckConstraint("probable_cases >= 0", name="probable_cases_non_negative"),
        sa.CheckConstraint("confirmed_cases >= 0", name="confirmed_cases_non_negative"),
        sa.CheckConstraint("total_cases >= 0", name="total_cases_non_negative"),
        sa.CheckConstraint("new_cases >= 0", name="new_cases_non_negative"),
        sa.CheckConstraint("deaths >= 0", name="deaths_non_negative"),
        sa.CheckConstraint("new_deaths >= 0", name="new_deaths_non_negative"),
        sa.CheckConstraint("recoveries >= 0", name="recoveries_non_negative"),
        sa.CheckConstraint("hospitalizations >= 0", name="hospitalizations_non_negative"),
        sa.CheckConstraint(
            "affected_admin_areas >= 0",
            name="affected_admin_areas_non_negative",
        ),
        sa.CheckConstraint("cfr >= 0 AND cfr <= 100", name="cfr_range"),
        sa.CheckConstraint(
            "extraction_confidence >= 0 AND extraction_confidence <= 1",
            name="extraction_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name="fk_event_observations_event_id_events",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name="fk_event_observations_signal_id_signals",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_event_observations"),
    )
    op.create_index(
        "ix_event_observations_event_date",
        "event_observations",
        ["event_id", "observation_date"],
    )

    op.create_table(
        "event_locations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("location_role", LOCATION_ROLE, nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("admin1", sa.Text(), nullable=True),
        sa.Column("admin2", sa.Text(), nullable=True),
        sa.Column("place_name", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("geometry", POINT, nullable=True),
        sa.Column("geocoding_source", sa.Text(), nullable=True),
        sa.Column("geocoding_confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("latitude >= -90 AND latitude <= 90", name="latitude_range"),
        sa.CheckConstraint("longitude >= -180 AND longitude <= 180", name="longitude_range"),
        sa.CheckConstraint(
            "geocoding_confidence >= 0 AND geocoding_confidence <= 1",
            name="geocoding_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
            name="fk_event_locations_event_id_events",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_event_locations"),
    )
    op.create_index(
        "ix_event_locations_geometry", "event_locations", ["geometry"], postgresql_using="gist"
    )


def downgrade() -> None:
    # PostGIS is intentionally left in place; the hosted project may share it.
    op.drop_index("ix_event_locations_geometry", table_name="event_locations")
    op.drop_table("event_locations")

    op.drop_index("ix_event_observations_event_date", table_name="event_observations")
    op.drop_table("event_observations")

    op.drop_table("event_signals")

    op.drop_index("ix_events_geometry", table_name="events")
    op.drop_index("ix_events_last_updated_at", table_name="events")
    op.drop_index("ix_events_country_code", table_name="events")
    op.drop_index("ix_events_disease_id", table_name="events")
    op.drop_index("ix_events_verification_status", table_name="events")
    op.drop_index("ix_events_status", table_name="events")
    op.drop_table("events")

    op.drop_index("ix_signals_processing_status", table_name="signals")
    op.drop_index("ix_signals_content_hash", table_name="signals")
    op.drop_index("ix_signals_canonical_url", table_name="signals")
    op.drop_index("ix_signals_published_at", table_name="signals")
    op.drop_index("ix_signals_source_id", table_name="signals")
    op.drop_table("signals")

    op.drop_table("pathogens")
    op.drop_table("diseases")
    op.drop_table("sources")
