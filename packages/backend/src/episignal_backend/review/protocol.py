"""Protocol definitions for the manual review repository seam."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from episignal_backend.db.types import ReviewReason, ReviewResolution, ReviewStatus
from episignal_backend.events.documents import SignalForMatching


@dataclass(frozen=True)
class LockedReviewCase:
    id: UUID
    signal_id: UUID
    reason: ReviewReason
    status: ReviewStatus


class ReviewRepository(Protocol):
    """Storage protocol required for review case resolution."""

    def lock_review_case(self, case_id: UUID) -> LockedReviewCase | None:
        """Lock and return the addressed review case, or None if not found."""
        ...

    def signal_for_review(self, signal_id: UUID) -> SignalForMatching | None:
        """Load signal matching context for event finalization."""
        ...

    def candidate_event_ids(self, case_id: UUID) -> set[UUID]:
        """Return the snapshot event IDs preserved when the case was opened."""
        ...

    def candidate_score(self, case_id: UUID, event_id: UUID) -> float | None:
        """Return the snapshot score for a specific candidate event."""
        ...

    def disease_exists(self, disease_id: UUID) -> bool:
        """Check if a canonical disease exists in the database."""
        ...

    def set_disease(self, signal_id: UUID, disease_id: UUID) -> None:
        """Assign a canonical disease to the signal."""
        ...

    def reset_retrieval(self, signal_id: UUID) -> None:
        """Reset retrieval attempts to zero while preserving needs_review."""
        ...

    def mark_classified(self, signal_id: UUID) -> None:
        """Advance signal to classified status for extraction retry."""
        ...

    def mark_extracted(self, signal_id: UUID) -> None:
        """Advance signal to extracted status for geocoding retry."""
        ...

    def mark_geocoded(self, signal_id: UUID) -> None:
        """Advance signal to geocoded status for event assembly."""
        ...

    def mark_dismissed(self, signal_id: UUID) -> None:
        """Move signal to terminal dismissed status."""
        ...

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
        """Update case state to resolved with audit metadata."""
        ...

    def commit(self) -> None:
        """Commit the ongoing transaction."""
        ...

    def rollback(self) -> None:
        """Roll back the ongoing transaction."""
        ...
