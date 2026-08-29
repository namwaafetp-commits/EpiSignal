from episignal_backend.db.types import (
    ProcessingStatus,
    ReviewReason,
    ReviewResolution,
    ReviewStatus,
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
