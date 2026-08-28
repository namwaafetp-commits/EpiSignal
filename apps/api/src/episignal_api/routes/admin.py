from datetime import datetime
from typing import Annotated
from uuid import UUID

from episignal_backend.db.types import (
    PipelineChain,
    PipelineRunStatus,
    PipelineTrigger,
)
from episignal_backend.radar import PipelineRunPage
from episignal_backend.schedule.documents import StageName
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from episignal_api.dependencies import get_pipeline_runs_page

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


class PipelineFailureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: StageName
    error: str | None


class PipelineRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    failures: list[PipelineFailureResponse]
    is_stale: bool


class PipelineRunListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[PipelineRunResponse]
    limit: int


@router.get("/pipeline-runs", response_model=PipelineRunListResponse)
def list_pipeline_runs(
    page: Annotated[PipelineRunPage, Depends(get_pipeline_runs_page)],
) -> PipelineRunListResponse:
    return PipelineRunListResponse.model_validate(page)
