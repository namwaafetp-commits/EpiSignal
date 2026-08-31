from datetime import date, datetime
from typing import Annotated, Any
from uuid import UUID

from episignal_backend.db.types import EventStatus, VerificationStatus
from episignal_backend.events.read import (
    DashboardEventPage,
    DashboardMapLevel,
    EventDetail,
    EventListPage,
    query_event_detail,
    query_event_observations,
    query_event_sources,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from episignal_api.dependencies import get_dashboard_events_page, get_event_page, get_session

router = APIRouter(prefix="/api/v1/events", tags=["events"])

SessionDep = Annotated[Any, Depends(get_session)]


class EventListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    headline: str | None
    summary: str | None
    disease: str | None
    event_type: str
    status: EventStatus
    verification_status: VerificationStatus
    country_code: str | None
    admin1: str | None
    admin2: str | None
    first_reported_at: datetime | None
    latest_report_at: datetime
    article_count: int
    last_summarized_at: datetime | None


class EventListResponse(BaseModel):
    items: list[EventListItemResponse]
    total: int
    limit: int
    offset: int


class DashboardEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    headline: str
    summary: str
    disease: str | None
    event_type: str
    status: EventStatus
    country_code: str | None
    admin1: str | None
    first_reported_at: datetime | None
    latest_report_at: datetime
    article_count: int
    last_summarized_at: datetime
    latitude: float | None
    longitude: float | None
    map_level: DashboardMapLevel | None


class DashboardEventsResponse(BaseModel):
    items: list[DashboardEventResponse]
    total: int


class EventSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class EventObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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


class EventSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    headline: str
    summary: str
    status: EventStatus
    latest_development: str | None
    uncertainties: list[str] | None
    model_id: str
    created_at: datetime


class EventDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    headline: str | None
    summary: str | None
    disease: str | None
    event_type: str
    status: EventStatus
    verification_status: VerificationStatus
    country_code: str | None
    admin1: str | None
    admin2: str | None
    first_reported_at: datetime | None
    latest_report_at: datetime
    article_count: int
    last_summarized_at: datetime | None
    early_signal_score: float | None
    evidence_score: float | None
    sources: list[EventSourceResponse]
    observations: list[EventObservationResponse]
    summaries: list[EventSummaryResponse]


@router.get("", response_model=EventListResponse)
def list_events(page: Annotated[EventListPage, Depends(get_event_page)]) -> EventListResponse:
    return EventListResponse(
        items=[EventListItemResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/dashboard", response_model=DashboardEventsResponse)
def dashboard_events(
    page: Annotated[DashboardEventPage, Depends(get_dashboard_events_page)],
) -> DashboardEventsResponse:
    return DashboardEventsResponse(
        items=[DashboardEventResponse.model_validate(item) for item in page.items],
        total=page.total,
    )


@router.get("/{public_id}", response_model=EventDetailResponse)
def get_event_detail(public_id: str, session: SessionDep) -> EventDetail:
    detail = query_event_detail(session, public_id=public_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return detail


@router.get("/{public_id}/sources", response_model=list[EventSourceResponse])
def get_event_sources(public_id: str, session: SessionDep) -> list[EventSourceResponse]:
    sources = query_event_sources(session, public_id=public_id)
    if sources is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return [EventSourceResponse.model_validate(source) for source in sources]


@router.get("/{public_id}/observations", response_model=list[EventObservationResponse])
def get_event_observations(public_id: str, session: SessionDep) -> list[EventObservationResponse]:
    observations = query_event_observations(session, public_id=public_id)
    if observations is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return [EventObservationResponse.model_validate(item) for item in observations]
