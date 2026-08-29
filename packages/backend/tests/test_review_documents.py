from uuid import uuid4

import pytest
from pydantic import ValidationError

from episignal_backend.db.types import (
    ProcessingStatus,
    ReviewReason,
    ReviewResolution,
    ReviewStatus,
)
from episignal_backend.review.documents import (
    ALLOWED_RESOLUTIONS,
    AssignDiseaseCommand,
    CreateEventCommand,
    DismissCommand,
    LinkEventCommand,
    ResolveReviewCommand,
    RetryExtractionCommand,
    RetryGeocodingCommand,
    RetryRetrievalCommand,
)


def test_review_vocabularies_are_closed() -> None:
    assert {value.value for value in ReviewReason} == {
        "retrieval_failed",
        "extraction_rejected",
        "disease_unresolved",
        "location_unresolved",
        "event_match_ambiguous",
        "content_integrity",
        "legacy_unclassified",
    }
    assert {value.value for value in ReviewStatus} == {"open", "resolved"}
    assert ReviewResolution.DISMISS == "dismiss"
    assert ProcessingStatus.DISMISSED == "dismissed"


def test_dismiss_requires_a_note() -> None:
    with pytest.raises(ValidationError):
        DismissCommand(
            case_id=uuid4(), action=ReviewResolution.DISMISS, reviewed_by="operator", note=" "
        )


def test_reviewed_by_cannot_be_blank() -> None:
    with pytest.raises(ValidationError):
        RetryRetrievalCommand(
            case_id=uuid4(), action=ReviewResolution.RETRY_RETRIEVAL, reviewed_by="   "
        )


def test_commands_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        RetryRetrievalCommand.model_validate(
            {
                "case_id": str(uuid4()),
                "action": "retry_retrieval",
                "reviewed_by": "operator",
                "extra_field": "disallowed",
            }
        )


def test_reason_action_matrix_is_closed() -> None:
    assert ALLOWED_RESOLUTIONS[ReviewReason.RETRIEVAL_FAILED] == frozenset({
        ReviewResolution.RETRY_RETRIEVAL,
        ReviewResolution.DISMISS,
    })
    assert ALLOWED_RESOLUTIONS[ReviewReason.EXTRACTION_REJECTED] == frozenset({
        ReviewResolution.RETRY_EXTRACTION,
        ReviewResolution.DISMISS,
    })
    assert ALLOWED_RESOLUTIONS[ReviewReason.DISEASE_UNRESOLVED] == frozenset({
        ReviewResolution.ASSIGN_DISEASE,
        ReviewResolution.DISMISS,
    })
    assert ALLOWED_RESOLUTIONS[ReviewReason.LOCATION_UNRESOLVED] == frozenset({
        ReviewResolution.RETRY_GEOCODING,
        ReviewResolution.DISMISS,
    })
    assert ALLOWED_RESOLUTIONS[ReviewReason.EVENT_MATCH_AMBIGUOUS] == frozenset({
        ReviewResolution.LINK_EVENT,
        ReviewResolution.CREATE_EVENT,
        ReviewResolution.DISMISS,
    })
    assert ALLOWED_RESOLUTIONS[ReviewReason.CONTENT_INTEGRITY] == frozenset({
        ReviewResolution.DISMISS,
    })
    assert ALLOWED_RESOLUTIONS[ReviewReason.LEGACY_UNCLASSIFIED] == frozenset({
        ReviewResolution.DISMISS,
    })
