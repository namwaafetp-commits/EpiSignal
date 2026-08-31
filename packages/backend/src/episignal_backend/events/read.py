"""Read-only access to stored events for the public API.

Separate from the matching repository on purpose: matching owns writes, this
module owns the public surface. Both read the same tables; nothing here can
mutate an event, an observation, or a source link.
"""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from episignal_backend.db.types import LocationRole, Precision
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
    town: str | None
    first_reported_at: datetime | None
    latest_report_at: datetime
    article_count: int
    last_summarized_at: datetime
    latitude: float | None
    longitude: float | None
    map_level: str | None


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
class EventObservationItem:
    observation_date: date | None
    reported_at: datetime | None
    suspected_cases: int | None
    probable_cases: int | None
    confirmed_cases: int | None
    total_cases: int | None
    new_cases: int | None
    deaths: int | None
    new_deaths: int | None
    hospitalizations: int | None
    notes: str | None
    extraction_confidence: float | None


@dataclass(frozen=True)
class EventSummaryItem:
    version: int
    headline: str
    summary: str
    status: str
    latest_development: str | None
    uncertainties: list[str] | None
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
    sources: tuple[EventSourceItem, ...]
    observations: tuple[EventObservationItem, ...]
    summaries: tuple[EventSummaryItem, ...]


def _dashboard_location(
    locations: tuple[EventLocation, ...],
    country_centroids: dict[str, tuple[float, float]],
    country_code: str | None,
) -> tuple[str | None, float | None, float | None, str | None]:
    place_locations = [
        location
        for location in locations
        if location.place_name and location.latitude is not None and location.longitude is not None
    ]
    place_locations.sort(
        key=lambda location: (
            location.location_role is not LocationRole.PRIMARY,
            str(location.id),
        )
    )
    if place_locations:
        place = place_locations[0]
        latitude = place.latitude
        longitude = place.longitude
        assert latitude is not None and longitude is not None
        return place.place_name, float(latitude), float(longitude), "town"

    if country_code is not None and country_code in country_centroids:
        latitude, longitude = country_centroids[country_code]
        return None, latitude, longitude, "country"

    return None, None, None, None


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

    event_ids = [event.id for event, _ in rows]
    location_rows = (
        session.execute(
            select(EventLocation)
            .where(EventLocation.event_id.in_(event_ids))
            .order_by(EventLocation.event_id, EventLocation.id)
        )
        .scalars()
        .all()
    )
    locations_by_event: dict[UUID, list[EventLocation]] = {}
    for location in location_rows:
        locations_by_event.setdefault(location.event_id, []).append(location)

    country_codes = {event.country_code for event, _ in rows if event.country_code is not None}
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
            disease=disease_name,
            event_type=event.event_type.value,
            status=event.status.value,
            country_code=event.country_code,
            town=location[0],
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
                tuple(locations_by_event.get(event.id, [])),
                country_centroids,
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
            observation_date=obs.observation_date,
            reported_at=obs.reported_at,
            suspected_cases=obs.suspected_cases,
            probable_cases=obs.probable_cases,
            confirmed_cases=obs.confirmed_cases,
            total_cases=obs.total_cases,
            new_cases=obs.new_cases,
            deaths=obs.deaths,
            new_deaths=obs.new_deaths,
            hospitalizations=obs.hospitalizations,
            notes=obs.notes,
            extraction_confidence=obs.extraction_confidence,
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
            status=summary.status.value,
            latest_development=summary.latest_development,
            uncertainties=summary.uncertainties,
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
