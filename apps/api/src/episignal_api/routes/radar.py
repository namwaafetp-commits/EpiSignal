from datetime import datetime
from typing import Annotated
from uuid import UUID

from episignal_backend.ai.schema import BriefPoint
from episignal_backend.db.types import (
    CredibilityTier,
    LocationRole,
    Precision,
    ProcessingStatus,
    SignalType,
    VerificationStatus,
)
from episignal_backend.radar import EventContextStatus, RadarPage
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from episignal_api.dependencies import get_radar_page

router = APIRouter(prefix="/api/v1/radar", tags=["radar"])


class RadarSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    url: str
    is_official: bool
    credibility_tier: CredibilityTier


class RadarLocationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: LocationRole
    precision: Precision
    label: str
    country_code: str | None
    latitude: float | None
    longitude: float | None


class RadarEventContextResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    public_id: str
    verification_status: VerificationStatus
    early_signal_score: float | None
    evidence_score: float | None


class RadarItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title_english: str
    brief: list[BriefPoint]
    signal_type: SignalType
    processing_status: ProcessingStatus
    published_at: datetime | None
    first_seen_at: datetime
    source: RadarSourceResponse
    extraction_confidence: float
    location: RadarLocationResponse | None
    event_context_status: EventContextStatus
    event: RadarEventContextResponse | None


class RadarEventGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_public_id: str
    event: RadarEventContextResponse
    signal_count: int
    representative_title: str
    representative_brief: list[BriefPoint]
    representative_location: RadarLocationResponse | None
    representative_source: RadarSourceResponse
    all_source_names: list[str]
    earliest_published_at: datetime | None
    latest_published_at: datetime | None
    first_seen_at: datetime


class RadarResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_groups: list[RadarEventGroupResponse]
    items: list[RadarItemResponse]
    window_start: datetime
    window_end: datetime
    hours: int
    limit: int


@router.get("", response_model=RadarResponse)
def get_radar(
    page: Annotated[RadarPage, Depends(get_radar_page)],
) -> RadarResponse:
    return RadarResponse.model_validate(page)
