"""Tests for review protocol contracts and repository interfaces."""

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID, uuid4

from episignal_backend.db.types import (
    ProcessingStatus,
    ReviewReason,
    ReviewResolution,
    ReviewStatus,
)
from episignal_backend.events.documents import SignalForMatching
from episignal_backend.review.protocol import LockedReviewCase, ReviewRepository


class FakeReviewRepository:
    def __init__(self, *, case_id: UUID | None = None, signal_id: UUID | None = None) -> None:
        self.case_id = case_id or uuid4()
        self.signal_id = signal_id or uuid4()
        self.reason = ReviewReason.RETRIEVAL_FAILED
        self.status = ReviewStatus.OPEN
        self.committed = False
        self.rolled_back = False
        self.resolutions: list[dict[str, object]] = []

    def lock_review_case(self, case_id: UUID) -> LockedReviewCase | None:
        if case_id != self.case_id:
            return None
        return LockedReviewCase(
            id=self.case_id,
            signal_id=self.signal_id,
            reason=self.reason,
            status=self.status,
        )

    def signal_for_review(self, signal_id: UUID) -> SignalForMatching | None:
        return None

    def candidate_event_ids(self, case_id: UUID) -> set[UUID]:
        return set()

    def candidate_score(self, case_id: UUID, event_id: UUID) -> float | None:
        return None

    def disease_exists(self, disease_id: UUID) -> bool:
        return True

    def set_disease(self, signal_id: UUID, disease_id: UUID) -> None:
        pass

    def reset_retrieval(self, signal_id: UUID) -> None:
        pass

    def mark_classified(self, signal_id: UUID) -> None:
        pass

    def mark_extracted(self, signal_id: UUID) -> None:
        pass

    def mark_geocoded(self, signal_id: UUID) -> None:
        pass

    def mark_dismissed(self, signal_id: UUID) -> None:
        pass

    def resolve_case(
        self,
        *,
        case_id: UUID,
        resolution: ReviewResolution,
        reviewed_by: str,
        note: str | None = None,
        selected_disease_id: UUID | None = None,
        selected_event_id: UUID | None = None,
        resolved_at: datetime | None = None,
    ) -> None:
        self.resolutions.append({
            "case_id": case_id,
            "resolution": resolution,
            "reviewed_by": reviewed_by,
            "note": note,
            "selected_disease_id": selected_disease_id,
            "selected_event_id": selected_event_id,
            "resolved_at": resolved_at,
        })
        self.status = ReviewStatus.RESOLVED

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


def test_fake_review_repository_implements_protocol() -> None:
    repo: ReviewRepository = FakeReviewRepository()
    locked = repo.lock_review_case(repo.case_id)  # type: ignore[attr-defined]
    assert locked is not None
    assert locked.status is ReviewStatus.OPEN
