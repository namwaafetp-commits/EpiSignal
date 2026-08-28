"""The storage boundary for story clustering, event matching, and scoring.

`EventRepository` declares the contract between the pure decision engine and
storage. The repository owns transactions: nothing above it knows what a session
is, which is why `commit` and `rollback` sit on the protocol.

This module imports neither SQLAlchemy nor httpx.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from episignal_backend.db.types import RelationshipType, VerificationStatus
from episignal_backend.events.documents import (
    CandidateEvent,
    LocationForMatching,
    SignalForMatching,
    StoryCluster,
)


class NoEventsToMatch(Exception):
    """Raised when no geocoded signals are available for matching."""


@runtime_checkable
class EventRepository(Protocol):
    """The storage contract for event matching, observation recording, and scoring."""

    def signals_to_match(self, limit: int, *, stale: bool = False) -> Sequence[SignalForMatching]:
        """Select signals at processing_status = 'geocoded' (or 'matched' if stale=True)."""
        ...

    def candidate_events(
        self,
        cluster: StoryCluster,
        *,
        recency_days: float = 90.0,
        distance_km: float = 50.0,
    ) -> Sequence[CandidateEvent]:
        """Retrieve candidate events matching the cluster's disease and spatial scope."""
        ...

    def create_event(self, cluster: StoryCluster) -> CandidateEvent:
        """Create a new event from a story cluster."""
        ...

    def attach_signal(
        self,
        event_id: UUID,
        signal_id: UUID,
        *,
        relationship_type: RelationshipType,
        match_score: float,
        is_primary: bool,
    ) -> None:
        """Attach a signal to an event in event_signals."""
        ...

    def record_observation(self, event_id: UUID, signal: SignalForMatching) -> None:
        """Record grounded counts from a signal as an event_observation."""
        ...

    def add_locations(self, event_id: UUID, locations: Sequence[LocationForMatching]) -> None:
        """Add new locations to event_locations without overwriting existing ones."""
        ...

    def apply_scores(
        self,
        event_id: UUID,
        early_signal_score: float,
        evidence_score: float,
        verification_status: VerificationStatus,
    ) -> None:
        """Update an event's early_signal_score, evidence_score, and verification_status."""
        ...

    def mark_matched(self, signal_id: UUID) -> None:
        """Advance a signal to processing_status = 'matched'."""
        ...

    def mark_needs_review(self, signal_id: UUID) -> None:
        """Route an unclusterable or refused signal to processing_status = 'needs_review'."""
        ...

    def commit(self) -> None:
        """Commit the current transaction."""
        ...

    def rollback(self) -> None:
        """Roll back the current transaction."""
        ...
