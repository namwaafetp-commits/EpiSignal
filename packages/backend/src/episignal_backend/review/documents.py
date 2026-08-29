"""Review commands, read models, domain exceptions, and reason-action matrix."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from episignal_backend.db.types import (
    LocationRole,
    Precision,
    ProcessingStatus,
    ReviewReason,
    ReviewResolution,
    VerificationStatus,
)


class ReviewCaseNotFound(Exception):
    """Raised when the specified review case does not exist."""

    def __init__(self, case_id: UUID) -> None:
        super().__init__(f"Review case {case_id} not found")
        self.case_id = case_id


class ReviewAlreadyResolved(Exception):
    """Raised when a resolution is attempted on an already-resolved case."""

    def __init__(self, case_id: UUID) -> None:
        super().__init__(f"Review case {case_id} is already resolved")
        self.case_id = case_id


class ReviewActionNotAllowed(Exception):
    """Raised when the requested action is incompatible with the case reason."""

    def __init__(self, reason: ReviewReason, action: ReviewResolution) -> None:
        super().__init__(f"Action {action} is not allowed for review reason {reason}")
        self.reason = reason
        self.action = action


class ReviewTargetStale(Exception):
    """Raised when a selected event candidate is no longer valid or in snapshot."""

    def __init__(self, target_id: UUID) -> None:
        super().__init__(f"Review target {target_id} is stale or not in qualifying snapshot")
        self.target_id = target_id


class DiseaseNotFound(Exception):
    """Raised when assigning a disease that does not exist in canonical catalog."""

    def __init__(self, disease_id: UUID) -> None:
        super().__init__(f"Canonical disease {disease_id} not found")
        self.disease_id = disease_id


ALLOWED_RESOLUTIONS: dict[ReviewReason, frozenset[ReviewResolution]] = {
    ReviewReason.RETRIEVAL_FAILED: frozenset(
        {
            ReviewResolution.RETRY_RETRIEVAL,
            ReviewResolution.DISMISS,
        }
    ),
    ReviewReason.EXTRACTION_REJECTED: frozenset(
        {
            ReviewResolution.RETRY_EXTRACTION,
            ReviewResolution.DISMISS,
        }
    ),
    ReviewReason.DISEASE_UNRESOLVED: frozenset(
        {
            ReviewResolution.ASSIGN_DISEASE,
            ReviewResolution.DISMISS,
        }
    ),
    ReviewReason.LOCATION_UNRESOLVED: frozenset(
        {
            ReviewResolution.RETRY_GEOCODING,
            ReviewResolution.DISMISS,
        }
    ),
    ReviewReason.EVENT_MATCH_AMBIGUOUS: frozenset(
        {
            ReviewResolution.LINK_EVENT,
            ReviewResolution.CREATE_EVENT,
            ReviewResolution.DISMISS,
        }
    ),
    ReviewReason.CONTENT_INTEGRITY: frozenset(
        {
            ReviewResolution.DISMISS,
        }
    ),
    ReviewReason.LEGACY_UNCLASSIFIED: frozenset(
        {
            ReviewResolution.DISMISS,
        }
    ),
}


class ReviewCommandBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: UUID
    reviewed_by: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("reviewed_by")
    @classmethod
    def reviewed_by_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reviewed_by must not be blank")
        return value

    @field_validator("note")
    @classmethod
    def note_is_not_blank_when_present(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("note must not be blank")
        return value


class RetryRetrievalCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.RETRY_RETRIEVAL] = ReviewResolution.RETRY_RETRIEVAL


class RetryExtractionCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.RETRY_EXTRACTION] = ReviewResolution.RETRY_EXTRACTION


class AssignDiseaseCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.ASSIGN_DISEASE] = ReviewResolution.ASSIGN_DISEASE
    disease_id: UUID


class RetryGeocodingCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.RETRY_GEOCODING] = ReviewResolution.RETRY_GEOCODING


class LinkEventCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.LINK_EVENT] = ReviewResolution.LINK_EVENT
    event_id: UUID


class CreateEventCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.CREATE_EVENT] = ReviewResolution.CREATE_EVENT


class DismissCommand(ReviewCommandBase):
    action: Literal[ReviewResolution.DISMISS] = ReviewResolution.DISMISS
    note: str = Field(min_length=1, max_length=1000)

    @field_validator("note")
    @classmethod
    def note_is_required_and_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("note must not be blank")
        return value


ResolveReviewCommand = Annotated[
    RetryRetrievalCommand
    | RetryExtractionCommand
    | AssignDiseaseCommand
    | RetryGeocodingCommand
    | LinkEventCommand
    | CreateEventCommand
    | DismissCommand,
    Field(discriminator="action"),
]


class ReviewCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: UUID
    signal_id: UUID
    resolution: ReviewResolution
    processing_status: ProcessingStatus
    selected_disease_id: UUID | None = None
    selected_event_id: UUID | None = None
    resolved_at: datetime


class ReviewCandidateEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: UUID
    public_id: str
    title: str
    verification_status: VerificationStatus
    match_score: float = Field(ge=0.0, le=1.0)


class ReviewSignalLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    location_role: LocationRole
    precision: Precision
    country_name: str | None = None
    admin1_name: str | None = None
    place_name: str | None = None
    resolved_name: str | None = None


class ReviewDiseaseOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    canonical_name: str


class ReviewQueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: UUID
    signal_id: UUID
    reason: ReviewReason
    opened_at: datetime
    title: str
    source_name: str
    source_url: str
    first_seen_at: datetime
    retrieval_attempts: int
    extracted_disease_text: str | None = None
    canonical_disease: str | None = None
    locations: list[ReviewSignalLocation] = Field(default_factory=list)
    candidate_events: list[ReviewCandidateEvent] = Field(default_factory=list)
    allowed_resolutions: list[ReviewResolution] = Field(default_factory=list)


class ReviewQueuePage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: list[ReviewQueueItem]
    total_open_cases: int
    disease_options: list[ReviewDiseaseOption]
    limit: int
    offset: int
