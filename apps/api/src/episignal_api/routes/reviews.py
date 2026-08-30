"""Review queue and resolution API routes."""

from collections.abc import Callable
from typing import Annotated, Literal
from uuid import UUID

from episignal_backend.db.types import ReviewResolution, VerificationStatus
from episignal_backend.review.documents import (
    AssignDiseaseCommand,
    CreateEventCommand,
    DiseaseNotFound,
    DismissCommand,
    LinkEventCommand,
    ResolveReviewCommand,
    RetryExtractionCommand,
    RetryGeocodingCommand,
    RetryRetrievalCommand,
    ReviewActionNotAllowed,
    ReviewAlreadyResolved,
    ReviewCaseNotFound,
    ReviewCaseResult,
    ReviewQueuePage,
    ReviewTargetStale,
)
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from episignal_api.dependencies import (
    get_review_queue_page,
    get_review_resolver,
    verify_admin_token,
)

router = APIRouter(prefix="/api/v1/admin/reviews", tags=["admin-reviews"])


class RetryRetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal[ReviewResolution.RETRY_RETRIEVAL] = ReviewResolution.RETRY_RETRIEVAL
    note: str | None = Field(default=None, max_length=1000)


class RetryExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal[ReviewResolution.RETRY_EXTRACTION] = ReviewResolution.RETRY_EXTRACTION
    note: str | None = Field(default=None, max_length=1000)


class AssignDiseaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal[ReviewResolution.ASSIGN_DISEASE] = ReviewResolution.ASSIGN_DISEASE
    disease_id: UUID
    note: str | None = Field(default=None, max_length=1000)


class RetryGeocodingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal[ReviewResolution.RETRY_GEOCODING] = ReviewResolution.RETRY_GEOCODING
    note: str | None = Field(default=None, max_length=1000)


class LinkEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal[ReviewResolution.LINK_EVENT] = ReviewResolution.LINK_EVENT
    target_event_id: UUID | None = None
    event_id: UUID | None = None
    note: str | None = Field(default=None, max_length=1000)

    @property
    def resolved_event_id(self) -> UUID:
        eid = self.event_id or self.target_event_id
        if eid is None:
            raise ValueError("event_id or target_event_id is required")
        return eid


class CreateEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal[ReviewResolution.CREATE_EVENT] = ReviewResolution.CREATE_EVENT
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    note: str | None = Field(default=None, max_length=1000)


class DismissRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: Literal[ReviewResolution.DISMISS] = ReviewResolution.DISMISS
    note: str = Field(min_length=1, max_length=1000)

    @field_validator("note")
    @classmethod
    def note_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("note must not be blank")
        return value


ReviewResolutionRequest = Annotated[
    RetryRetrievalRequest
    | RetryExtractionRequest
    | AssignDiseaseRequest
    | RetryGeocodingRequest
    | LinkEventRequest
    | CreateEventRequest
    | DismissRequest,
    Field(discriminator="action"),
]


def _build_command(
    request: ReviewResolutionRequest,
    case_id: UUID,
    reviewed_by: str,
) -> ResolveReviewCommand:
    if isinstance(request, RetryRetrievalRequest):
        return RetryRetrievalCommand(case_id=case_id, reviewed_by=reviewed_by, note=request.note)
    elif isinstance(request, RetryExtractionRequest):
        return RetryExtractionCommand(case_id=case_id, reviewed_by=reviewed_by, note=request.note)
    elif isinstance(request, AssignDiseaseRequest):
        return AssignDiseaseCommand(
            case_id=case_id,
            reviewed_by=reviewed_by,
            disease_id=request.disease_id,
            note=request.note,
        )
    elif isinstance(request, RetryGeocodingRequest):
        return RetryGeocodingCommand(case_id=case_id, reviewed_by=reviewed_by, note=request.note)
    elif isinstance(request, LinkEventRequest):
        return LinkEventCommand(
            case_id=case_id,
            reviewed_by=reviewed_by,
            event_id=request.resolved_event_id,
            note=request.note,
        )
    elif isinstance(request, CreateEventRequest):
        return CreateEventCommand(
            case_id=case_id,
            reviewed_by=reviewed_by,
            note=request.note,
        )
    elif isinstance(request, DismissRequest):
        return DismissCommand(case_id=case_id, reviewed_by=reviewed_by, note=request.note)
    raise ValueError(f"Unknown request type: {type(request)}")


@router.get("", response_model=ReviewQueuePage)
def list_review_queue(
    _admin: Annotated[str, Depends(verify_admin_token)],
    page: Annotated[ReviewQueuePage, Depends(get_review_queue_page)],
) -> ReviewQueuePage:
    """Retrieve filtered review cases awaiting administrator action."""
    return page


@router.post("/{case_id}/resolve", response_model=ReviewCaseResult)
def resolve_case(
    case_id: UUID,
    body: ReviewResolutionRequest,
    _admin: Annotated[str, Depends(verify_admin_token)],
    resolver: Annotated[
        Callable[[UUID, ResolveReviewCommand], ReviewCaseResult],
        Depends(get_review_resolver),
    ],
) -> ReviewCaseResult:
    """Resolve an open review case with a valid action and transition signal state."""
    command = _build_command(body, case_id=case_id, reviewed_by=_admin)
    try:
        return resolver(case_id, command)
    except ReviewCaseNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (ReviewAlreadyResolved, ReviewTargetStale) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (ReviewActionNotAllowed, DiseaseNotFound) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
