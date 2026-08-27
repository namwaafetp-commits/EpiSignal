from datetime import datetime
from typing import Annotated
from uuid import UUID

from episignal_backend.evidence import EvidencePage
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from episignal_api.dependencies import get_evidence_page

router = APIRouter(prefix="/api/v1/signals", tags=["signals"])


class SignalEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_name: str
    title: str
    raw_text: str
    url: str
    published_at: datetime | None
    retrieved_at: datetime


class SignalListResponse(BaseModel):
    items: list[SignalEvidenceResponse]
    total: int
    source_count: int
    limit: int
    offset: int


@router.get("", response_model=SignalListResponse)
def list_signals(
    page: Annotated[EvidencePage, Depends(get_evidence_page)],
) -> SignalListResponse:
    return SignalListResponse(
        items=[SignalEvidenceResponse.model_validate(item) for item in page.items],
        total=page.total,
        source_count=page.source_count,
        limit=page.limit,
        offset=page.offset,
    )
