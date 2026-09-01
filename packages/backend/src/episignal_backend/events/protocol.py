"""The storage boundary for story clustering, event matching, and scoring.

`EventRepository` declares the contract between the pure decision engine and
storage. The repository owns transactions: nothing above it knows what a session
is, which is why `commit` and `rollback` sit on the protocol.

This module imports neither SQLAlchemy nor httpx.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from episignal_backend.ai.documents import AiRequestRecord
from episignal_backend.ai.schema import BriefPoint
from episignal_backend.db.types import (
    RelationshipType,
    VerificationStatus,
)
from episignal_backend.events.documents import (
    CandidateEvent,
    EventForSummary,
    LocationForMatching,
    SignalForMatching,
    StoryCluster,
)


class NoEventsToMatch(Exception):
    """Raised when no extracted signals are available for matching."""


@runtime_checkable
class EventRepository(Protocol):
    """The storage contract for event matching, observation recording, and scoring."""

    def signals_to_match(self, limit: int, *, stale: bool = False) -> Sequence[SignalForMatching]:
        """Select signals at processing_status = 'extracted' (or matched when stale)."""
        ...

    def candidate_events(
        self,
        cluster: StoryCluster,
        *,
        lookback_days: int = 7,
        limit: int = 20,
        distance_km: float = 50.0,
    ) -> Sequence[CandidateEvent]:
        """Retrieve recent same-disease, same-country candidate events."""
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

    def latest_brief(self, event_id: UUID) -> tuple[BriefPoint, ...] | None:
        """The most recently reported brief already attached to an event.

        Read before the new attach lands, so the delta pass compares against
        what the event was, not what this run just made it.
        """
        ...

    def apply_delta(self, event_id: UUID, signal_id: UUID, delta: dict[str, object]) -> None:
        """Write the delta pass output onto one observation row. Nothing else moves."""
        ...

    def record_ai_request(self, record: AiRequestRecord) -> None:
        """Write one cost row. The delta pass is costed like every other request."""
        ...

    def events_awaiting_summary(
        self, *, limit: int, max_age_hours: int
    ) -> Sequence[EventForSummary]:
        """Events that may need a new summary, with the sources to summarize from."""
        ...

    def store_summary(
        self,
        *,
        event_id: UUID,
        headline: str,
        summary: str,
        trajectory: str,
        snapshot: dict[str, object],
        key_driver: str,
        response: str,
        risk: str,
        model_id: str,
        source_signal_ids: list[UUID],
        counts: dict[str, object] | None,
        now: datetime | None = None,
    ) -> int:
        """Append one versioned summary and denormalize it onto the event.

        Returns the version that was written (1 for the first summary).
        """
        ...

    def commit(self) -> None:
        """Commit the current transaction."""
        ...

    def rollback(self) -> None:
        """Roll back the current transaction."""
        ...
