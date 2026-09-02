"""Read-only access to stored events for the public API.

Separate from the matching repository on purpose: matching owns writes, this
module owns the public surface. Both read the same tables; nothing here can
mutate an event, an observation, or a source link.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from episignal_backend.db.types import Precision
from episignal_backend.geocode.normalize import ascii_form, normalized_form
from episignal_backend.models import (
    Disease,
    Event,
    EventLocation,
    EventObservation,
    EventSignal,
    EventSummary,
    GazetteerPlace,
    Signal,
    Source,
)

DashboardMapLevel = Literal["admin1", "country"]


def _stored_disease_text(session: Session, event_id: UUID) -> str | None:
    from episignal_backend.events.repository import read_stored_extraction

    payload = session.execute(
        select(Signal.ai_extraction)
        .join(EventSignal, EventSignal.signal_id == Signal.id)
        .where(EventSignal.event_id == event_id)
        .order_by(EventSignal.is_primary.desc(), Signal.first_seen_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    extraction = read_stored_extraction(payload)
    return str(extraction.disease) if extraction is not None and extraction.disease else None


@dataclass(frozen=True)
class EventListItem:
    public_id: str
    headline: str | None
    summary: str | None
    disease: str | None
    event_type: str
    status: str
    verification_status: str
    country_code: str | None
    admin1: str | None
    admin2: str | None
    first_reported_at: datetime | None
    latest_report_at: datetime
    article_count: int
    last_summarized_at: datetime | None


@dataclass(frozen=True)
class EventListPage:
    items: tuple[EventListItem, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class DashboardEventItem:
    public_id: str
    headline: str
    summary: str
    disease: str | None
    event_type: str
    status: str
    country_code: str | None
    admin1: str | None
    first_reported_at: datetime | None
    latest_report_at: datetime
    article_count: int
    last_summarized_at: datetime
    latitude: float | None
    longitude: float | None
    map_level: DashboardMapLevel | None


@dataclass(frozen=True)
class DashboardEventPage:
    items: tuple[DashboardEventItem, ...]
    total: int


@dataclass(frozen=True)
class EventSourceItem:
    signal_id: UUID
    source_name: str
    is_official: bool
    credibility_tier: str
    title: str
    url: str
    published_at: datetime | None
    first_seen_at: datetime
    relationship_type: str
    is_primary: bool


@dataclass(frozen=True)
class EventLocationItem:
    location_role: str
    precision: str
    country_code: str | None
    admin1: str | None
    admin2: str | None
    place_name: str | None
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True)
class EventObservationItem:
    signal_id: UUID
    observation_date: date | None
    reported_at: datetime | None
    notes: str | None
    material_facts: dict[str, object] | None = None


@dataclass(frozen=True)
class EventSummaryItem:
    version: int
    headline: str
    summary: str
    trajectory: str
    snapshot: tuple[str, ...] | None
    key_driver: str | None
    response: str | None
    risk: str | None
    model_id: str
    created_at: datetime


@dataclass(frozen=True)
class EventDetail:
    public_id: str
    headline: str | None
    summary: str | None
    disease: str | None
    event_type: str
    status: str
    verification_status: str
    country_code: str | None
    admin1: str | None
    admin2: str | None
    first_reported_at: datetime | None
    latest_report_at: datetime
    article_count: int
    last_summarized_at: datetime | None
    early_signal_score: float | None
    evidence_score: float | None
    locations: tuple[EventLocationItem, ...]
    sources: tuple[EventSourceItem, ...]
    observations: tuple[EventObservationItem, ...]
    summaries: tuple[EventSummaryItem, ...]


def normalize_summary_snapshot(value: object) -> tuple[str, ...] | None:
    """Expose new fact arrays and legacy snapshot objects uniformly."""
    if isinstance(value, (list, tuple)):
        facts = value
    elif isinstance(value, dict):
        facts = []
        cases = value.get("cases")
        geographic_extent = value.get("geographic_extent")
        if isinstance(cases, str) and cases.strip():
            facts.append(cases)
        deaths = value.get("deaths")
        cfr = value.get("cfr")
        if isinstance(deaths, str) and deaths.strip() and isinstance(cfr, str) and cfr.strip():
            facts.append(f"{deaths} / {cfr}")
        elif isinstance(deaths, str) and deaths.strip():
            facts.append(deaths)
        elif isinstance(cfr, str) and cfr.strip():
            facts.append(cfr)
        if isinstance(geographic_extent, str) and geographic_extent.strip():
            facts.append(geographic_extent)
    else:
        return None

    normalized = tuple(
        " ".join(item.split()) for item in facts if isinstance(item, str) and item.strip()
    )
    return normalized or None


def _dashboard_location(
    admin1: str | None,
    country_centroids: dict[str, tuple[float, float]],
    admin1_centroids: dict[tuple[str, str], tuple[str, float, float]],
    country_code: str | None,
) -> tuple[str | None, float | None, float | None, DashboardMapLevel | None]:
    if admin1 is not None and country_code is not None:
        centroid = admin1_centroids.get((country_code, admin1))
        if centroid is None:
            centroid = admin1_centroids.get((country_code, normalized_form(admin1)))
        if centroid is None:
            centroid = admin1_centroids.get((country_code, ascii_form(admin1)))
        if centroid is not None:
            resolved_name, latitude, longitude = centroid
            return resolved_name, latitude, longitude, "admin1"

    if country_code is not None and country_code in country_centroids:
        latitude, longitude = country_centroids[country_code]
        return admin1, latitude, longitude, "country"

    return admin1, None, None, None


def query_dashboard_events(session: Session) -> DashboardEventPage:
    """Return every stored event with a completed, non-empty summary."""
    conditions = [
        Event.summary.is_not(None),
        func.btrim(Event.summary) != "",
        Event.last_summarized_at.is_not(None),
    ]
    rows = session.execute(
        select(Event, Disease.canonical_name)
        .outerjoin(Disease, Disease.id == Event.disease_id)
        .where(*conditions)
        .order_by(Event.last_updated_at.desc(), Event.id.desc())
    ).all()

    if not rows:
        return DashboardEventPage(items=(), total=0)

    country_codes = {event.country_code for event, _ in rows if event.country_code is not None}
    admin1_centroids: dict[tuple[str, str], tuple[str, float, float]] = {}
    if country_codes:
        admin1_rows = session.execute(
            select(
                GazetteerPlace.country_code,
                GazetteerPlace.admin1_code,
                GazetteerPlace.name,
                GazetteerPlace.normalized_name,
                GazetteerPlace.ascii_name,
                GazetteerPlace.latitude,
                GazetteerPlace.longitude,
            )
            .where(
                GazetteerPlace.country_code.in_(country_codes),
                GazetteerPlace.precision == Precision.ADMIN1,
                GazetteerPlace.admin1_code.is_not(None),
            )
            .order_by(GazetteerPlace.country_code, GazetteerPlace.geonames_id)
        ).all()
        for (
            code,
            admin1_code,
            name,
            normalized_name,
            ascii_name,
            latitude,
            longitude,
        ) in admin1_rows:
            centroid = (name, float(latitude), float(longitude))
            if admin1_code is not None:
                admin1_centroids.setdefault((code, admin1_code), centroid)
            admin1_centroids.setdefault((code, normalized_name), centroid)
            admin1_centroids.setdefault((code, ascii_name), centroid)

    country_centroids: dict[str, tuple[float, float]] = {}
    if country_codes:
        centroid_rows = session.execute(
            select(GazetteerPlace.country_code, GazetteerPlace.latitude, GazetteerPlace.longitude)
            .where(
                GazetteerPlace.country_code.in_(country_codes),
                GazetteerPlace.precision == Precision.COUNTRY,
                GazetteerPlace.admin1_code.is_(None),
            )
            .order_by(GazetteerPlace.country_code, GazetteerPlace.geonames_id)
        ).all()
        for code, latitude, longitude in centroid_rows:
            country_centroids.setdefault(code, (float(latitude), float(longitude)))

    items = tuple(
        DashboardEventItem(
            public_id=event.public_id,
            headline=event.headline,
            summary=event.summary,
            disease=disease_name or _stored_disease_text(session, event.id),
            event_type=event.event_type.value,
            status=event.status.value,
            country_code=event.country_code,
            admin1=location[0],
            first_reported_at=event.first_signal_at,
            latest_report_at=event.last_updated_at,
            article_count=event.article_count,
            last_summarized_at=event.last_summarized_at,
            latitude=location[1],
            longitude=location[2],
            map_level=location[3],
        )
        for event, disease_name in rows
        for location in (
            _dashboard_location(
                event.admin1,
                country_centroids,
                admin1_centroids,
                event.country_code,
            ),
        )
    )
    return DashboardEventPage(items=items, total=len(items))


def query_event_list(
    session: Session,
    *,
    limit: int = 20,
    offset: int = 0,
    disease: str | None = None,
    country: str | None = None,
    admin1: str | None = None,
    status: str | None = None,
    verification_status: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> EventListPage:
    """Events with the plan's filters, most recently updated first."""
    conditions = []
    if disease is not None:
        conditions.append(func.lower(Disease.canonical_name) == disease.lower())
    if country is not None:
        conditions.append(Event.country_code == country.upper())
    if admin1 is not None:
        conditions.append(Event.admin1.ilike(f"%{admin1}%"))
    if status is not None:
        conditions.append(Event.status == status)
    if verification_status is not None:
        conditions.append(Event.verification_status == verification_status)
    if start_date is not None:
        conditions.append(Event.last_updated_at >= start_date)
    if end_date is not None:
        conditions.append(Event.last_updated_at < end_date)

    total = session.execute(
        select(func.count(Event.id))
        .select_from(Event)
        .outerjoin(Disease, Disease.id == Event.disease_id)
        .where(*conditions)
    ).scalar_one()

    rows = session.execute(
        select(Event, Disease.canonical_name)
        .outerjoin(Disease, Disease.id == Event.disease_id)
        .where(*conditions)
        .order_by(Event.last_updated_at.desc(), Event.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    items = tuple(
        EventListItem(
            public_id=event.public_id,
            headline=event.headline,
            summary=event.summary,
            disease=disease_name or _stored_disease_text(session, event.id),
            event_type=event.event_type.value,
            status=event.status.value,
            verification_status=event.verification_status.value,
            country_code=event.country_code,
            admin1=event.admin1,
            admin2=event.admin2,
            first_reported_at=event.first_signal_at,
            latest_report_at=event.last_updated_at,
            article_count=event.article_count,
            last_summarized_at=event.last_summarized_at,
        )
        for event, disease_name in rows
    )

    return EventListPage(items=items, total=total, limit=limit, offset=offset)


def query_event_detail(
    session: Session,
    *,
    public_id: str,
) -> EventDetail | None:
    """One event by public id, with its sources, observations, and summaries."""
    row = session.execute(
        select(Event, Disease.canonical_name)
        .outerjoin(Disease, Disease.id == Event.disease_id)
        .where(Event.public_id == public_id)
    ).first()
    if row is None:
        return None
    event, disease_name = row
    if disease_name is None:
        disease_name = _stored_disease_text(session, event.id)

    location_rows = (
        session.execute(
            select(EventLocation)
            .where(EventLocation.event_id == event.id)
            .order_by(EventLocation.location_role, EventLocation.id)
        )
        .scalars()
        .all()
    )
    locations = tuple(
        EventLocationItem(
            location_role=location.location_role.value,
            precision=(
                "place"
                if location.place_name
                else "admin1"
                if location.admin1
                else "country"
                if location.country_code
                else "unresolved"
            ),
            country_code=location.country_code,
            admin1=location.admin1,
            admin2=location.admin2,
            place_name=location.place_name,
            latitude=location.latitude,
            longitude=location.longitude,
        )
        for location in location_rows
    )

    source_rows = session.execute(
        select(
            EventSignal.signal_id,
            Source.name,
            Source.is_official,
            Source.credibility_tier,
            Signal.title,
            Signal.url,
            Signal.published_at,
            Signal.first_seen_at,
            EventSignal.relationship_type,
            EventSignal.is_primary,
        )
        .select_from(EventSignal)
        .join(Signal, Signal.id == EventSignal.signal_id)
        .join(Source, Source.id == Signal.source_id)
        .where(EventSignal.event_id == event.id)
        .order_by(
            EventSignal.is_primary.desc(),
            func.coalesce(Signal.published_at, Signal.first_seen_at).desc(),
            Signal.id.desc(),
        )
    ).all()
    sources = tuple(
        EventSourceItem(
            signal_id=signal_id,
            source_name=source_name,
            is_official=is_official,
            credibility_tier=credibility_tier.value,
            title=title,
            url=url,
            published_at=published_at,
            first_seen_at=first_seen_at,
            relationship_type=relationship_type.value,
            is_primary=is_primary,
        )
        for (
            signal_id,
            source_name,
            is_official,
            credibility_tier,
            title,
            url,
            published_at,
            first_seen_at,
            relationship_type,
            is_primary,
        ) in source_rows
    )

    observation_rows = (
        session.execute(
            select(EventObservation)
            .where(EventObservation.event_id == event.id)
            .order_by(
                func.coalesce(EventObservation.reported_at, EventObservation.created_at).asc(),
                EventObservation.created_at.asc(),
            )
        )
        .scalars()
        .all()
    )
    observations = tuple(
        EventObservationItem(
            signal_id=obs.signal_id,
            observation_date=obs.observation_date,
            reported_at=obs.reported_at,
            notes=obs.notes,
            material_facts=obs.material_facts,
        )
        for obs in observation_rows
    )

    summary_rows = (
        session.execute(
            select(EventSummary)
            .where(EventSummary.event_id == event.id)
            .order_by(EventSummary.version.desc())
        )
        .scalars()
        .all()
    )
    summaries = tuple(
        EventSummaryItem(
            version=summary.version,
            headline=summary.headline,
            summary=summary.summary,
            trajectory=summary.trajectory or "Unclear",
            snapshot=normalize_summary_snapshot(summary.snapshot),
            key_driver=summary.key_driver,
            response=summary.response,
            risk=summary.risk,
            model_id=summary.model_id,
            created_at=summary.created_at,
        )
        for summary in summary_rows
    )

    return EventDetail(
        public_id=event.public_id,
        headline=event.headline,
        summary=event.summary,
        disease=disease_name,
        event_type=event.event_type.value,
        status=event.status.value,
        verification_status=event.verification_status.value,
        country_code=event.country_code,
        admin1=event.admin1,
        admin2=event.admin2,
        first_reported_at=event.first_signal_at,
        latest_report_at=event.last_updated_at,
        article_count=event.article_count,
        last_summarized_at=event.last_summarized_at,
        early_signal_score=event.early_signal_score,
        evidence_score=event.evidence_score,
        locations=locations,
        sources=sources,
        observations=observations,
        summaries=summaries,
    )


def query_event_sources(session: Session, *, public_id: str) -> tuple[EventSourceItem, ...] | None:
    detail = query_event_detail(session, public_id=public_id)
    return detail.sources if detail is not None else None


def query_event_observations(
    session: Session, *, public_id: str
) -> tuple[EventObservationItem, ...] | None:
    detail = query_event_detail(session, public_id=public_id)
    return detail.observations if detail is not None else None
