"""Contracts crossing the gazetteer seam and the storage seam.

A `ResolvedLocation` deliberately carries both sides of the answer. The
`*_name` fields hold what the extraction said, unmodified; the `resolved_*`,
`admin*`, and coordinate fields hold what the gazetteer answered. A coarsened
result is therefore never mistakable for a place-level hit, and "why this
coordinate" is answerable from one row.

This module imports neither SQLAlchemy nor httpx.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from episignal_backend.db.types import LocationRole, Precision


class MatchForm(StrEnum):
    """How a name was matched. Tried in this order and never merged.

    An exact match must not be diluted by the collisions that folding
    introduces, so the forms are separate rungs rather than one query.
    """

    EXACT = "exact"
    ASCII = "ascii"
    ALTERNATE = "alternate"


class ExtractedPlace(BaseModel):
    """One location as the extraction reported it, before any resolution.

    Every field but the role is optional, because a model reports what the
    article said and an article can name a country with no town, a town with no
    country, or neither.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: LocationRole
    country_name: str | None = Field(default=None, max_length=100)
    admin1_name: str | None = Field(default=None, max_length=200)
    place_name: str | None = Field(default=None, max_length=200)


class Candidate(BaseModel):
    """One gazetteer row offered as a possible answer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    geonames_id: int
    name: str = Field(min_length=1)
    precision: Precision
    country_code: str = Field(min_length=2, max_length=2)
    admin1_code: str | None = None
    admin2_code: str | None = None
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)


class ResolvedLocation(BaseModel):
    """What one extracted place resolved to, at whatever precision was reached."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: LocationRole
    country_name: str | None = None
    admin1_name: str | None = None
    place_name: str | None = None
    precision: Precision
    geonames_id: int | None = None
    resolved_name: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    admin1: str | None = None
    admin2: str | None = None
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    # Absent, not zero. A zero would claim the system assessed this location and
    # found it worthless; a null says it has no assessment to offer.
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class GeocodableSignal(BaseModel):
    """A signal at `extracted`, with the places its extraction named."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    locations: tuple[ExtractedPlace, ...] = ()
