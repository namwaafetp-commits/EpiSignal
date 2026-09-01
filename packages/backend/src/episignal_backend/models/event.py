from datetime import date, datetime
from typing import Any
from uuid import UUID

from geoalchemy2 import Geography
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin, TimestampMixin
from episignal_backend.db.types import (
    EventStatus,
    EventType,
    LocationRole,
    RelationshipType,
    VerificationStatus,
    vocabulary,
)


def point_4326() -> Geography:
    return Geography(geometry_type="POINT", srid=4326, spatial_index=False)


class Event(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="longitude_range"),
        CheckConstraint(
            "early_signal_score >= 0 AND early_signal_score <= 1",
            name="early_signal_score_range",
        ),
        CheckConstraint(
            "evidence_score >= 0 AND evidence_score <= 1",
            name="evidence_score_range",
        ),
        Index("ix_events_status", "status"),
        Index("ix_events_verification_status", "verification_status"),
        Index("ix_events_disease_id", "disease_id"),
        Index("ix_events_country_code", "country_code"),
        Index("ix_events_last_updated_at", "last_updated_at"),
        Index("ix_events_geometry", "geometry", postgresql_using="gist"),
    )

    public_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    disease_id: Mapped[UUID | None] = mapped_column(ForeignKey("diseases.id", ondelete="RESTRICT"))
    pathogen_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("pathogens.id", ondelete="RESTRICT")
    )
    event_type: Mapped[EventType] = mapped_column(
        vocabulary(EventType, "event_type_values"),
        nullable=False,
        default=EventType.OTHER,
    )
    status: Mapped[EventStatus] = mapped_column(
        vocabulary(EventStatus, "event_status_values"),
        nullable=False,
        default=EventStatus.MONITORING,
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        vocabulary(VerificationStatus, "verification_status_values"),
        nullable=False,
        default=VerificationStatus.UNVERIFIED,
    )
    country_code: Mapped[str | None] = mapped_column(String(2))
    admin1: Mapped[str | None] = mapped_column(Text)
    admin2: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    geometry: Mapped[Any | None] = mapped_column(point_4326())
    first_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_start_date: Mapped[date | None] = mapped_column(Date)
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    early_signal_score: Mapped[float | None] = mapped_column(Float)
    evidence_score: Mapped[float | None] = mapped_column(Float)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    # Lean MVP event summary surface. `headline`/`summary` are the latest
    # accepted summary; the versioned history lives in `event_summaries`.
    headline: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    article_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_summarized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventSignal(Base):
    __tablename__ = "event_signals"
    __table_args__ = (
        CheckConstraint("match_score >= 0 AND match_score <= 1", name="match_score_range"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), primary_key=True
    )
    relationship_type: Mapped[RelationshipType] = mapped_column(
        vocabulary(RelationshipType, "relationship_type_values"),
        nullable=False,
        default=RelationshipType.SUPPORTING_SOURCE,
    )
    match_score: Mapped[float | None] = mapped_column(Float)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EventObservation(IdentityMixin, Base):
    __tablename__ = "event_observations"
    __table_args__ = (
        CheckConstraint("suspected_cases >= 0", name="suspected_cases_non_negative"),
        CheckConstraint("probable_cases >= 0", name="probable_cases_non_negative"),
        CheckConstraint("confirmed_cases >= 0", name="confirmed_cases_non_negative"),
        CheckConstraint("total_cases >= 0", name="total_cases_non_negative"),
        CheckConstraint("new_cases >= 0", name="new_cases_non_negative"),
        CheckConstraint("deaths >= 0", name="deaths_non_negative"),
        CheckConstraint("new_deaths >= 0", name="new_deaths_non_negative"),
        CheckConstraint("recoveries >= 0", name="recoveries_non_negative"),
        CheckConstraint("hospitalizations >= 0", name="hospitalizations_non_negative"),
        CheckConstraint("affected_admin_areas >= 0", name="affected_admin_areas_non_negative"),
        CheckConstraint("cfr >= 0 AND cfr <= 100", name="cfr_range"),
        CheckConstraint(
            "extraction_confidence >= 0 AND extraction_confidence <= 1",
            name="extraction_confidence_range",
        ),
        Index("ix_event_observations_event_date", "event_id", "observation_date"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="RESTRICT"), nullable=False
    )
    observation_date: Mapped[date | None] = mapped_column(Date)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspected_cases: Mapped[int | None] = mapped_column(Integer)
    probable_cases: Mapped[int | None] = mapped_column(Integer)
    confirmed_cases: Mapped[int | None] = mapped_column(Integer)
    total_cases: Mapped[int | None] = mapped_column(Integer)
    new_cases: Mapped[int | None] = mapped_column(Integer)
    deaths: Mapped[int | None] = mapped_column(Integer)
    new_deaths: Mapped[int | None] = mapped_column(Integer)
    recoveries: Mapped[int | None] = mapped_column(Integer)
    hospitalizations: Mapped[int | None] = mapped_column(Integer)
    cfr: Mapped[float | None] = mapped_column(Float)
    affected_admin_areas: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    # The delta pass output written onto this observation when it followed up
    # an already-observed event: the updated five-slot brief plus what changed.
    # Absent on every observation that was not the product of a follow-up.
    delta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Validated extraction facts used by event summary evidence and material
    # change detection. This is additive history, never an overwritten total.
    material_facts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EventLocation(IdentityMixin, Base):
    __tablename__ = "event_locations"
    __table_args__ = (
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="longitude_range"),
        CheckConstraint(
            "geocoding_confidence >= 0 AND geocoding_confidence <= 1",
            name="geocoding_confidence_range",
        ),
        Index("ix_event_locations_geometry", "geometry", postgresql_using="gist"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    location_role: Mapped[LocationRole] = mapped_column(
        vocabulary(LocationRole, "location_role_values"),
        nullable=False,
        default=LocationRole.PRIMARY,
    )
    country_code: Mapped[str | None] = mapped_column(String(2))
    admin1: Mapped[str | None] = mapped_column(Text)
    admin2: Mapped[str | None] = mapped_column(Text)
    place_name: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    geometry: Mapped[Any | None] = mapped_column(point_4326())
    geocoding_source: Mapped[str | None] = mapped_column(Text)
    geocoding_confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EventSummary(IdentityMixin, Base):
    """One generated event-level flash brief, versioned and never overwritten.

    Each material update appends a row; the newest row is what
    ``events.headline``/``events.summary`` denormalize for the public surface.
    The older ``latest_development``/``uncertainties`` columns remain nullable
    for mixed-version rows but are no longer part of the summary contract.
    """

    __tablename__ = "event_summaries"
    __table_args__ = (
        UniqueConstraint("event_id", "version", name="uq_event_summaries_event_version"),
        Index("ix_event_summaries_event", "event_id"),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[EventStatus] = mapped_column(
        vocabulary(EventStatus, "event_status_values"),
        nullable=False,
        default=EventStatus.MONITORING,
    )
    latest_development: Mapped[str | None] = mapped_column(Text)
    uncertainties: Mapped[list[str] | None] = mapped_column(JSONB)
    trajectory: Mapped[str | None] = mapped_column(Text)
    snapshot: Mapped[list[str] | dict[str, Any] | None] = mapped_column(JSONB)
    key_driver: Mapped[str | None] = mapped_column(Text)
    response: Mapped[str | None] = mapped_column(Text)
    risk: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_signal_ids: Mapped[list[UUID] | None] = mapped_column(JSONB)
    # The epidemiological snapshot this summary was written against, so the next
    # material-change check compares like with like instead of re-reading prose.
    counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
