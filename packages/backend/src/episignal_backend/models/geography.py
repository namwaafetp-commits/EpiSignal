from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
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
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin
from episignal_backend.db.types import LocationRole, Precision, vocabulary
from episignal_backend.models.event import point_4326


class GazetteerPlace(Base):
    """Reviewed reference data. Written by seeding, never by a pass.

    Keyed on `geonames_id` rather than a generated UUID: the id is stable across
    dumps, which is what makes reseeding an update rather than a duplication.
    """

    __tablename__ = "gazetteer_places"
    __table_args__ = (
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="longitude_range"),
        Index("ix_gazetteer_places_normalized_name", "normalized_name"),
        Index("ix_gazetteer_places_ascii_name", "ascii_name"),
        Index(
            "ix_gazetteer_places_scope",
            "country_code",
            "admin1_code",
            "normalized_name",
        ),
        Index("ix_gazetteer_places_alternate_names", "alternate_names", postgresql_using="gin"),
        Index("ix_gazetteer_places_precision", "precision"),
        Index("ix_gazetteer_places_geometry", "geometry", postgresql_using="gist"),
    )

    geonames_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    ascii_name: Mapped[str] = mapped_column(Text, nullable=False)
    alternate_names: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    feature_code: Mapped[str] = mapped_column(String(10), nullable=False)
    precision: Mapped[Precision] = mapped_column(
        vocabulary(Precision, "precision_values"), nullable=False
    )
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    admin1_code: Mapped[str | None] = mapped_column(String(20))
    admin2_code: Mapped[str | None] = mapped_column(String(80))
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    geometry: Mapped[Any | None] = mapped_column(point_4326())
    # Stored but never consulted to break a tie. Kept because D2 may weigh a
    # match by how large the place is, which is a different question from which
    # place was meant.
    population: Mapped[int | None] = mapped_column(BigInteger)


class SignalLocation(IdentityMixin, Base):
    """One extracted place, and whatever the gazetteer could say about it.

    Both sides are recorded. The `*_name` columns are the extraction's own
    strings, unmodified; everything else is the resolution. `precision` is what
    keeps a province centroid from reading like a town.
    """

    __tablename__ = "signal_locations"
    __table_args__ = (
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="longitude_range"),
        CheckConstraint(
            "geocoding_confidence >= 0 AND geocoding_confidence <= 1",
            name="geocoding_confidence_range",
        ),
        Index("ix_signal_locations_signal_id", "signal_id"),
        Index("ix_signal_locations_precision", "precision"),
        Index("ix_signal_locations_country_code", "country_code"),
        Index("ix_signal_locations_geometry", "geometry", postgresql_using="gist"),
        Index("ix_signal_locations_geocoding_source", "geocoding_source"),
    )

    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), nullable=False
    )
    location_role: Mapped[LocationRole] = mapped_column(
        vocabulary(LocationRole, "location_role_values"),
        nullable=False,
        default=LocationRole.PRIMARY,
    )
    country_name: Mapped[str | None] = mapped_column(Text)
    admin1_name: Mapped[str | None] = mapped_column(Text)
    place_name: Mapped[str | None] = mapped_column(Text)
    precision: Mapped[Precision] = mapped_column(
        vocabulary(Precision, "precision_values"), nullable=False
    )
    geonames_id: Mapped[int | None] = mapped_column(Integer)
    resolved_name: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(String(2))
    admin1: Mapped[str | None] = mapped_column(Text)
    admin2: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    geometry: Mapped[Any | None] = mapped_column(point_4326())
    geocoding_source: Mapped[str | None] = mapped_column(Text)
    geocoding_confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GeocodeCache(IdentityMixin, Base):
    """One place name answered outside the gazetteer, kept so it is paid for once.

    Keyed on the whitespace-collapsed lower-case query plus the country scope
    it was searched under; a NULL scope is the worldwide lookup. Rows are
    unreviewed data written only by the geocoding pass and safe to drop: the
    worst a refill costs is the external call it saves.
    """

    __tablename__ = "geocode_cache"
    __table_args__ = (
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="longitude_range"),
        UniqueConstraint("normalized_query", "country_code"),
        Index("ix_geocode_cache_country_code", "country_code"),
    )

    normalized_query: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))
    resolved_name: Mapped[str] = mapped_column(Text, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(
        Text, nullable=False, default="nominatim", server_default="nominatim"
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
