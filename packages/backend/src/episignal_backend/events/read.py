"""Read-only access to stored events for the public API.

Separate from the matching repository on purpose: matching owns writes, this
module owns the public surface. Both read the same tables; nothing here can
mutate an event, an observation, or a source link.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from episignal_backend.db.types import HostSector, Precision
from episignal_backend.disease_groups import (
    CANONICAL_DISEASE_GROUPS,
    disease_group_for,
    disease_group_label,
)
from episignal_backend.events.host_sector import derive_event_host_sector
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


def _stored_disease_text_bulk(session: Session, event_ids: list[UUID]) -> dict[UUID, str]:
    from episignal_backend.events.repository import read_stored_extraction

    rows = session.execute(
        select(
            EventSignal.event_id,
            Signal.ai_extraction,
        )
        .join(Signal, Signal.id == EventSignal.signal_id)
        .where(EventSignal.event_id.in_(event_ids))
        .order_by(
            EventSignal.event_id,
            EventSignal.is_primary.desc(),
            Signal.first_seen_at.desc(),
        )
    ).all()
    selected_event_ids: set[UUID] = set()
    fallback_disease_by_event_id: dict[UUID, str] = {}
    for event_id, payload in rows:
        if event_id in selected_event_ids:
            continue
        selected_event_ids.add(event_id)
        extraction = read_stored_extraction(payload)
        if extraction is not None and extraction.disease:
            fallback_disease_by_event_id[event_id] = str(extraction.disease)
    return fallback_disease_by_event_id


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
    disease_group: str = "unknown"
    disease_group_label: str = "Unknown / unclassified"
    host_sector: HostSector = HostSector.UNKNOWN
    summary_payload: dict[str, object] | None = None


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
    disease_group: str = "unknown"
    disease_group_label: str = "Unknown / unclassified"
    host_sector: HostSector = HostSector.UNKNOWN
    summary_payload: dict[str, object] | None = None


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
    summary_payload: dict[str, object] | None = None


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
    disease_group: str = "unknown"
    disease_group_label: str = "Unknown / unclassified"
    host_sector: HostSector = HostSector.UNKNOWN
    summary_payload: dict[str, object] | None = None


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


def _event_host_sectors(session: Session, event_ids: list[UUID]) -> dict[UUID, HostSector]:
    if not event_ids:
        return {}
    rows = session.execute(
        select(EventSignal.event_id, Signal.host_sector)
        .join(Signal, Signal.id == EventSignal.signal_id)
        .where(EventSignal.event_id.in_(event_ids))
    ).all()
    values: dict[UUID, list[HostSector | None]] = {}
    for event_id, host_sector in rows:
        values.setdefault(event_id, []).append(host_sector)
    return {event_id: derive_event_host_sector(sectors) for event_id, sectors in values.items()}


def _unpack_event_row(row: Sequence[object]) -> tuple[Event, str | None, str | None]:
    """Read old two-column repository fakes while production uses disease slug too."""
    if len(row) == 2:
        event, disease_name = row
        return event, disease_name, None  # type: ignore[return-value]
    event, disease_name, disease_slug = row[:3]
    return event, disease_name, disease_slug  # type: ignore[return-value]


def query_dashboard_events(
    session: Session,
    *,
    host_sector: str | None = None,
    disease_group: str | None = None,
) -> DashboardEventPage:
    """Return every stored event with a completed, non-empty summary."""
    conditions = [
        Event.summary.is_not(None),
        func.btrim(Event.summary) != "",
        Event.last_summarized_at.is_not(None),
    ]
    rows = session.execute(
        select(Event, Disease.canonical_name, Disease.slug)
        .outerjoin(Disease, Disease.id == Event.disease_id)
        .where(*conditions)
        .order_by(Event.last_updated_at.desc(), Event.id.desc())
    ).all()

    if not rows:
        return DashboardEventPage(items=(), total=0)

    normalized_rows = [_unpack_event_row(row) for row in rows]
    host_sectors = (
        _event_host_sectors(session, [event.id for event, _, _ in normalized_rows])
        if len(rows[0]) > 2
        else {}
    )
    fallback_event_ids = [
        event.id for event, disease_name, _ in normalized_rows if not disease_name
    ]
    fallback_disease_by_event_id = (
        _stored_disease_text_bulk(session, fallback_event_ids) if fallback_event_ids else {}
    )

    country_codes = {
        event.country_code for event, _, _ in normalized_rows if event.country_code is not None
    }
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

    items_list: list[DashboardEventItem] = []
    for event, disease_name, disease_slug in normalized_rows:
        group = disease_group_for(disease_slug)
        sector = host_sectors.get(event.id, HostSector.UNKNOWN)
        if host_sector == "human" and sector not in {HostSector.HUMAN, HostSector.BOTH}:
            continue
        if host_sector == "animal" and sector not in {HostSector.ANIMAL, HostSector.BOTH}:
            continue
        if disease_group is not None and group.value != disease_group:
            continue
        location = _dashboard_location(
            event.admin1,
            country_centroids,
            admin1_centroids,
            event.country_code,
        )
        items_list.append(
            DashboardEventItem(
                public_id=event.public_id,
                headline=event.headline or event.public_id,
                summary=event.summary or "",
                disease=disease_name or fallback_disease_by_event_id.get(event.id),
                event_type=event.event_type.value,
                status=event.status.value,
                country_code=event.country_code,
                admin1=location[0],
                first_reported_at=event.first_signal_at,
                latest_report_at=event.last_updated_at,
                article_count=event.article_count,
                last_summarized_at=event.last_summarized_at or event.last_updated_at,
                latitude=location[1],
                longitude=location[2],
                map_level=location[3],
                disease_group=group.value,
                disease_group_label=disease_group_label(group),
                host_sector=sector,
                summary_payload=getattr(event, "summary_payload", None),
            )
        )
    items = tuple(items_list)
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
    host_sector: str | None = None,
    disease_group: str | None = None,
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
    if host_sector in {"human", "animal"}:
        accepted = [host_sector, "both"]
        conditions.append(
            Event.id.in_(
                select(EventSignal.event_id)
                .join(Signal, Signal.id == EventSignal.signal_id)
                .where(Signal.host_sector.in_(accepted))
            )
        )
    if disease_group is not None:
        group_slugs = [
            slug for slug, group in CANONICAL_DISEASE_GROUPS.items() if group.value == disease_group
        ]
        if disease_group == "unknown":
            conditions.append(or_(Disease.id.is_(None), Disease.slug.in_(group_slugs)))
        else:
            conditions.append(Disease.slug.in_(group_slugs))

    total = session.execute(
        select(func.count(Event.id))
        .select_from(Event)
        .outerjoin(Disease, Disease.id == Event.disease_id)
        .where(*conditions)
    ).scalar_one()

    rows = session.execute(
        select(Event, Disease.canonical_name, Disease.slug)
        .outerjoin(Disease, Disease.id == Event.disease_id)
        .where(*conditions)
        .order_by(Event.last_updated_at.desc(), Event.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    normalized_rows = [_unpack_event_row(row) for row in rows]
    host_sectors = (
        _event_host_sectors(session, [event.id for event, _, _ in normalized_rows])
        if rows and len(rows[0]) > 2
        else {}
    )
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
            disease_group=disease_group_for(disease_slug).value,
            disease_group_label=disease_group_label(disease_group_for(disease_slug)),
            host_sector=host_sectors.get(event.id, HostSector.UNKNOWN),
            summary_payload=getattr(event, "summary_payload", None),
        )
        for event, disease_name, disease_slug in normalized_rows
    )

    return EventListPage(items=items, total=total, limit=limit, offset=offset)


def query_event_detail(
    session: Session,
    *,
    public_id: str,
) -> EventDetail | None:
    """One event by public id, with its sources, observations, and summaries."""
    row = session.execute(
        select(Event, Disease.canonical_name, Disease.slug)
        .outerjoin(Disease, Disease.id == Event.disease_id)
        .where(Event.public_id == public_id)
    ).first()
    if row is None:
        return None
    event, disease_name, disease_slug = _unpack_event_row(row)
    if disease_name is None:
        disease_name = _stored_disease_text(session, event.id)
    event_host_sector = (
        _event_host_sectors(session, [event.id]).get(event.id, HostSector.UNKNOWN)
        if len(row) > 2
        else HostSector.UNKNOWN
    )
    event_group = disease_group_for(disease_slug)

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
            summary_payload=getattr(summary, "summary_payload", None),
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
        disease_group=event_group.value,
        disease_group_label=disease_group_label(event_group),
        host_sector=event_host_sector,
        summary_payload=getattr(event, "summary_payload", None),
    )


def query_event_sources(session: Session, *, public_id: str) -> tuple[EventSourceItem, ...] | None:
    detail = query_event_detail(session, public_id=public_id)
    return detail.sources if detail is not None else None


def query_event_observations(
    session: Session, *, public_id: str
) -> tuple[EventObservationItem, ...] | None:
    detail = query_event_detail(session, public_id=public_id)
    return detail.observations if detail is not None else None
