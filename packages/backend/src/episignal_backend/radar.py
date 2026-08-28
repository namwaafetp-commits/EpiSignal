"""The signal radar read model and queries.

Provides read-only access to recent early signals with C2 briefs,
representative locations, source credibility, and optional attached event context.
Also provides counts-only pipeline run monitoring.
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from episignal_backend.ai.schema import BRIEF_SLOT_COUNT, BriefPoint, StoredExtractionPayload
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
from episignal_backend.models import (
    Event,
    EventSignal,
    Signal,
    SignalLocation,
    Source,
)
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


def query_radar(
    session: Session,
    *,
    now: datetime,
    hours: int = 48,
    limit: int = 50,
) -> RadarPage:
    """Query recent high-quality signals and assemble the radar read model."""
    window_start = now - timedelta(hours=hours)
    window_end = now

    effective_time = func.coalesce(Signal.published_at, Signal.first_seen_at)

    event_heat_subquery = (
        select(func.max(Event.early_signal_score))
        .select_from(EventSignal)
        .join(Event, Event.id == EventSignal.event_id)
        .where(EventSignal.signal_id == Signal.id)
        .group_by(EventSignal.signal_id)
        .having(func.count(EventSignal.event_id) == 1)
        .scalar_subquery()
    )

    statement = (
        select(
            Signal.id,
            Signal.url,
            Signal.processing_status,
            Signal.signal_type,
            Signal.published_at,
            Signal.first_seen_at,
            Signal.ai_extraction,
            Source.name.label("source_name"),
            Source.is_official.label("source_is_official"),
            Source.credibility_tier.label("source_credibility_tier"),
        )
        .join(Source, Source.id == Signal.source_id)
        .where(
            Signal.ai_extraction.op("->>")("extraction_schema_version") == "2",
            effective_time >= window_start,
            effective_time <= window_end,
            Signal.processing_status.in_(
                [
                    ProcessingStatus.EXTRACTED,
                    ProcessingStatus.GEOCODED,
                    ProcessingStatus.MATCHED,
                    ProcessingStatus.PUBLISHED,
                ]
            ),
            Signal.duplicate_of_signal_id.is_(None),
        )
        .order_by(
            effective_time.desc(),
            event_heat_subquery.desc().nulls_last(),
            Signal.id.desc(),
        )
        .limit(limit)
    )

    rows = session.execute(statement).all()
    if not rows:
        return RadarPage(
            items=(),
            window_start=window_start,
            window_end=window_end,
            hours=hours,
            limit=limit,
        )

    signal_ids = [row.id for row in rows]

    locations_stmt = select(SignalLocation).where(SignalLocation.signal_id.in_(signal_ids))
    location_results = session.execute(locations_stmt).scalars().all()
    locations_by_signal: dict[UUID, list[SignalLocation]] = defaultdict(list)
    for loc in location_results:
        locations_by_signal[loc.signal_id].append(loc)

    events_stmt = (
        select(
            EventSignal.signal_id,
            Event.public_id,
            Event.verification_status,
            Event.early_signal_score,
            Event.evidence_score,
        )
        .join(Event, Event.id == EventSignal.event_id)
        .where(EventSignal.signal_id.in_(signal_ids))
    )
    event_results = session.execute(events_stmt).all()
    events_by_signal: dict[UUID, list[RadarEventContext]] = defaultdict(list)
    for ev in event_results:
        events_by_signal[ev.signal_id].append(
            RadarEventContext(
                public_id=ev.public_id,
                verification_status=ev.verification_status,
                early_signal_score=ev.early_signal_score,
                evidence_score=ev.evidence_score,
            )
        )

    items: list[RadarItem] = []
    for row in rows:
        if not row.ai_extraction:
            continue
        try:
            payload = StoredExtractionPayload.model_validate(row.ai_extraction)
        except Exception:
            continue

        if not payload.title_english or len(payload.brief) != BRIEF_SLOT_COUNT:
            continue

        linked_events = events_by_signal.get(row.id, [])
        if len(linked_events) == 0:
            event_context_status = EventContextStatus.NONE
            event = None
        elif len(linked_events) == 1:
            event_context_status = EventContextStatus.ATTACHED
            event = linked_events[0]
        else:
            event_context_status = EventContextStatus.AMBIGUOUS
            event = None

        location = choose_representative_location(locations_by_signal.get(row.id, []))

        source = RadarSource(
            name=row.source_name,
            url=row.url,
            is_official=row.source_is_official,
            credibility_tier=row.source_credibility_tier,
        )

        items.append(
            RadarItem(
                id=row.id,
                title_english=payload.title_english,
                brief=payload.brief,
                signal_type=row.signal_type,
                processing_status=row.processing_status,
                published_at=row.published_at,
                first_seen_at=row.first_seen_at,
                source=source,
                extraction_confidence=payload.confidence,
                location=location,
                event_context_status=event_context_status,
                event=event,
            )
        )

    return RadarPage(
        items=tuple(items),
        window_start=window_start,
        window_end=window_end,
        hours=hours,
        limit=limit,
    )
