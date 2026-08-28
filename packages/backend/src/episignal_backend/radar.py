"""The signal radar read model and queries.

Provides read-only access to recent early signals with C2 briefs,
representative locations, source credibility, and optional attached event context.
Also provides counts-only pipeline run monitoring.
"""

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
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
    PipelineRun,
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
class RadarLocation:
    role: LocationRole
    precision: Precision
    label: str
    country_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class RadarSource:
    name: str
    url: str
    is_official: bool
    credibility_tier: CredibilityTier


@dataclass(frozen=True)
class RadarEventContext:
    public_id: str
    verification_status: VerificationStatus
    early_signal_score: float
    evidence_score: float


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
    """Select the representative location for a signal following deterministic tie-breaking.

    Hierarchy:
    1. Primary location (role == LocationRole.PRIMARY) preferred over non-primary.
    2. Finest precision rank (place > admin2 > admin1 > country > unresolved).
    3. Lowest UUID ascending as deterministic tie-breaker.
    """
    if not locations:
        return None

    primary = [loc for loc in locations if loc.location_role == LocationRole.PRIMARY]
    candidates = primary if primary else list(locations)

    chosen = min(
        candidates,
        key=lambda loc: (_PRECISION_RANK.get(loc.precision, 99), str(loc.id)),
    )

    label = (
        chosen.resolved_name
        or chosen.place_name
        or chosen.admin2
        or chosen.admin1
        or chosen.admin1_name
        or chosen.country_name
        or "Unknown"
    )

    lat = chosen.latitude
    lon = chosen.longitude
    if (
        chosen.precision == Precision.UNRESOLVED
        or lat is None
        or lon is None
        or not (-90.0 <= lat <= 90.0)
        or not (-180.0 <= lon <= 180.0)
    ):
        latitude = None
        longitude = None
    else:
        latitude = float(lat)
        longitude = float(lon)

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
    """Query recent signals with representative locations and event context."""
    window_end = now
    window_start = now - timedelta(hours=hours)

    effective_time = func.coalesce(Signal.published_at, Signal.first_seen_at)

    event_heat_subquery = (
        select(Event.early_signal_score)
        .join(EventSignal, EventSignal.event_id == Event.id)
        .where(EventSignal.signal_id == Signal.id)
        .order_by(Event.early_signal_score.desc().nulls_last())
        .limit(1)
        .scalar_subquery()
    )

    base_statement = (
        select(
            Signal.id,
            Signal.url,
            Signal.signal_type,
            Signal.processing_status,
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
    )

    chunk_size = max(limit, 20)
    max_scan = max(limit * 5, 100)
    offset = 0

    valid_rows_and_payloads: list[tuple[Any, StoredExtractionPayload]] = []
    while len(valid_rows_and_payloads) < limit and offset < max_scan:
        chunk_stmt = base_statement.offset(offset).limit(chunk_size)
        chunk_rows = session.execute(chunk_stmt).all()
        if not chunk_rows:
            break
        offset += len(chunk_rows)
        for row in chunk_rows:
            if not row.ai_extraction:
                continue
            try:
                payload = StoredExtractionPayload.model_validate(row.ai_extraction)
            except Exception:
                continue
            if not payload.title_english or len(payload.brief) != BRIEF_SLOT_COUNT:
                continue
            valid_rows_and_payloads.append((row, payload))
            if len(valid_rows_and_payloads) == limit:
                break
        if len(chunk_rows) < chunk_size:
            break

    if not valid_rows_and_payloads:
        return RadarPage(
            items=(),
            window_start=window_start,
            window_end=window_end,
            hours=hours,
            limit=limit,
        )

    signal_ids = [row.id for row, _ in valid_rows_and_payloads]

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
    for row, payload in valid_rows_and_payloads:
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

        assert payload.title_english is not None

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


def _normalize_stage_counts(raw: Any) -> dict[str, dict[str, int]]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, int]] = {}
    for stage_name, counts in raw.items():
        if isinstance(stage_name, str) and isinstance(counts, dict):
            valid_counts: dict[str, int] = {}
            for k, v in counts.items():
                if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool):
                    valid_counts[k] = v
            normalized[stage_name] = valid_counts
    return normalized


def _normalize_backlog(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, int] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool):
            normalized[k] = v
    return normalized


_VALID_EXCEPTION_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _safe_error_name(error_val: Any) -> str | None:
    if not isinstance(error_val, str):
        return None
    cleaned = error_val.strip()
    if _VALID_EXCEPTION_NAME.match(cleaned):
        return cleaned
    return None


def _normalize_failures(raw: Any) -> tuple[PipelineFailure, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    failures: list[PipelineFailure] = []
    for item in raw:
        if isinstance(item, str):
            try:
                stage = StageName(item)
                failures.append(PipelineFailure(stage=stage, error=None))
            except ValueError:
                continue
        elif isinstance(item, dict):
            stage_val = item.get("stage")
            if not isinstance(stage_val, str):
                continue
            try:
                stage = StageName(stage_val)
            except ValueError:
                continue
            error_val = item.get("error")
            failures.append(PipelineFailure(stage=stage, error=_safe_error_name(error_val)))
    return tuple(failures)


def query_pipeline_runs(
    session: Session,
    *,
    now: datetime,
    stale_after_minutes: int,
    limit: int = 20,
) -> PipelineRunPage:
    """Query recent pipeline runs for read-only operational monitoring."""
    statement = select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(limit)
    runs = session.execute(statement).scalars().all()

    items: list[PipelineRunItem] = []
    for run in runs:
        is_stale = (
            run.status == PipelineRunStatus.RUNNING
            and run.finished_at is None
            and (now - run.started_at).total_seconds() > 2 * stale_after_minutes * 60
        )
        items.append(
            PipelineRunItem(
                id=run.id,
                chain=run.chain,
                trigger=run.trigger,
                status=run.status,
                started_at=run.started_at,
                finished_at=run.finished_at,
                window_start=run.window_start,
                window_end=run.window_end,
                stage_counts=_normalize_stage_counts(run.stage_counts),
                backlog=_normalize_backlog(run.backlog),
                failures=_normalize_failures(run.failed_stages),
                is_stale=is_stale,
            )
        )

    return PipelineRunPage(items=tuple(items), limit=limit)
