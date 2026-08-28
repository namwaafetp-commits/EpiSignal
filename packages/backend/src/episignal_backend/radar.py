"""The signal radar read model and queries.

Provides read-only access to recent early signals with C2 briefs,
representative locations, source credibility, and optional attached event context.
Also provides counts-only pipeline run monitoring.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from episignal_backend.ai.schema import BriefPoint
from episignal_backend.db.types import (
    CredibilityTier,
    LocationRole,
    PipelineChain,
    PipelineRunStatus,
    PipelineTrigger,
    Precision,
    ProcessingStatus,
    SignalType,
    VerificationStatus,
)
from episignal_backend.models import SignalLocation
from episignal_backend.schedule.documents import StageName


class EventContextStatus(StrEnum):
    NONE = "none"
    ATTACHED = "attached"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class RadarSource:
    name: str
    url: str
    is_official: bool
    credibility_tier: CredibilityTier


@dataclass(frozen=True)
class RadarLocation:
    role: LocationRole
    precision: Precision
    label: str
    country_code: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class RadarEventContext:
    public_id: str
    verification_status: VerificationStatus
    early_signal_score: float | None
    evidence_score: float | None


@dataclass(frozen=True)
class RadarItem:
    id: UUID
    title_english: str
    brief: tuple[BriefPoint, ...]
    signal_type: SignalType
    processing_status: ProcessingStatus
    published_at: datetime | None
    first_seen_at: datetime
    source: RadarSource
    extraction_confidence: float
    location: RadarLocation | None
    event_context_status: EventContextStatus
    event: RadarEventContext | None


@dataclass(frozen=True)
class RadarPage:
    items: tuple[RadarItem, ...]
    window_start: datetime
    window_end: datetime
    hours: int
    limit: int


@dataclass(frozen=True)
class PipelineFailure:
    stage: StageName
    error: str | None


@dataclass(frozen=True)
class PipelineRunItem:
    id: UUID
    chain: PipelineChain
    trigger: PipelineTrigger
    status: PipelineRunStatus
    started_at: datetime
    finished_at: datetime | None
    window_start: datetime | None
    window_end: datetime | None
    stage_counts: dict[str, dict[str, int]]
    backlog: dict[str, int]
    failures: tuple[PipelineFailure, ...]
    is_stale: bool


@dataclass(frozen=True)
class PipelineRunPage:
    items: tuple[PipelineRunItem, ...]
    limit: int


_PRECISION_RANK: dict[Precision, int] = {
    Precision.PLACE: 1,
    Precision.ADMIN2: 2,
    Precision.ADMIN1: 3,
    Precision.COUNTRY: 4,
    Precision.UNRESOLVED: 5,
}


def choose_representative_location(
    locations: Sequence[SignalLocation],
) -> RadarLocation | None:
    """Select one representative location for the signal map.

    1. Consider primary locations first; if none, consider all locations.
    2. Sort by highest recorded precision (place > admin2 > admin1 > country > unresolved).
    3. Break equal-precision ties by ascending location UUID.
    4. Label fallback: resolved_name -> place_name -> admin2 -> admin1 -> country_name.
    5. Unresolved or incomplete coordinates return latitude=None, longitude=None.
    """
    if not locations:
        return None

    primary = [loc for loc in locations if loc.location_role == LocationRole.PRIMARY]
    candidates = primary if primary else list(locations)

    chosen = min(
        candidates,
        key=lambda loc: (_PRECISION_RANK.get(loc.precision, 99), loc.id),
    )

    label = (
        chosen.resolved_name
        or chosen.place_name
        or chosen.admin2
        or chosen.admin1
        or chosen.country_name
        or ""
    )

    if (
        chosen.precision == Precision.UNRESOLVED
        or chosen.latitude is None
        or chosen.longitude is None
    ):
        latitude = None
        longitude = None
    else:
        latitude = float(chosen.latitude)
        longitude = float(chosen.longitude)

    return RadarLocation(
        role=chosen.location_role,
        precision=chosen.precision,
        label=label,
        country_code=chosen.country_code,
        latitude=latitude,
        longitude=longitude,
    )
