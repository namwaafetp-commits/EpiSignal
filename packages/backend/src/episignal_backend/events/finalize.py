"""Shared event finalization for event assembly and manual review resolution.

Owns the single implementation of attaching signals to existing events,
creating new events, recording observations, adding locations, updating scores,
and optionally triggering delta generation.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from uuid import UUID

from episignal_backend.ai.documents import ModelSpec
from episignal_backend.ai.ladder import cost_row
from episignal_backend.ai.protocol import ChatModel
from episignal_backend.ai.schema import BriefPoint
from episignal_backend.db.types import AiPurpose, RelationshipType
from episignal_backend.events.delta import DeltaOutcome, delta_payload, run_delta
from episignal_backend.events.documents import (
    CandidateEvent,
    SignalForMatching,
    StoryCluster,
)
from episignal_backend.events.protocol import EventRepository
from episignal_backend.events.score import (
    DEFAULT_EARLY_SIGNAL_WEIGHTS,
    DEFAULT_EVIDENCE_WEIGHTS,
    early_signal_score,
    evidence_score,
    verification_status,
)


def _resolve_now(now: Callable[[], datetime] | datetime | None) -> datetime:
    if callable(now):
        return now()
    if isinstance(now, datetime):
        return now
    return datetime.now(UTC)


def finalize_event_link(
    repo: EventRepository,
    *,
    event_id: UUID,
    signal: SignalForMatching,
    relationship_type: RelationshipType = RelationshipType.SUPPORTING_SOURCE,
    match_score: float = 1.0,
    is_primary: bool = False,
    delta_model: ChatModel | None = None,
    delta_spec: ModelSpec | None = None,
    followup_window_days: float | None = None,
    early_signal_weights: Mapping[str, float] = DEFAULT_EARLY_SIGNAL_WEIGHTS,
    evidence_weights: Mapping[str, float] = DEFAULT_EVIDENCE_WEIGHTS,
    now: Callable[[], datetime] | datetime | None = None,
) -> int:
    """Attach one signal to an existing event, update scores, and maybe apply delta."""
    moment = _resolve_now(now)
    previous_brief = repo.latest_brief(event_id)

    repo.attach_signal(
        event_id,
        signal.signal_id,
        relationship_type=relationship_type,
        match_score=match_score,
        is_primary=is_primary,
    )
    repo.record_observation(event_id, signal)
    repo.add_locations(event_id, signal.locations)
    repo.mark_matched(signal.signal_id)

    early = early_signal_score([signal], now=moment, weights=early_signal_weights)
    evid = evidence_score([signal], weights=evidence_weights)
    v_status = verification_status([signal])
    repo.apply_scores(event_id, early.total, evid.total, v_status)

    deltas_applied = 0
    if (
        delta_model is not None
        and delta_spec is not None
        and previous_brief is not None
        and signal.extraction is not None
        and signal.extraction.brief
    ):
        target_brief = signal.extraction.brief
        result = run_delta(
            delta_model, delta_spec, previous=previous_brief, new=target_brief
        )
        if result.attempt is not None:
            repo.record_ai_request(
                cost_row(
                    result.attempt,
                    purpose=AiPurpose.FOLLOW_UP,
                    signal_id=signal.signal_id,
                    batch_size=1,
                    at=moment,
                )
            )
        if result.outcome is DeltaOutcome.ACCEPTED and result.delta is not None:
            repo.apply_delta(event_id, signal.signal_id, delta_payload(result.delta))
            deltas_applied = 1

    return deltas_applied


def finalize_event_creation(
    repo: EventRepository,
    *,
    cluster: StoryCluster,
    early_signal_weights: Mapping[str, float] = DEFAULT_EARLY_SIGNAL_WEIGHTS,
    evidence_weights: Mapping[str, float] = DEFAULT_EVIDENCE_WEIGHTS,
    now: Callable[[], datetime] | datetime | None = None,
) -> CandidateEvent:
    """Create a new event from a story cluster and attach all member signals."""
    moment = _resolve_now(now)
    created = repo.create_event(cluster)
    event_id = created.event_id

    for idx, sig in enumerate(cluster.signals):
        is_primary = idx == 0
        rel_type = (
            RelationshipType.INITIAL_REPORT
            if is_primary
            else RelationshipType.SUPPORTING_SOURCE
        )
        repo.attach_signal(
            event_id,
            sig.signal_id,
            relationship_type=rel_type,
            match_score=1.0,
            is_primary=is_primary,
        )
        repo.record_observation(event_id, sig)
        repo.add_locations(event_id, sig.locations)
        repo.mark_matched(sig.signal_id)

    early = early_signal_score(cluster.signals, now=moment, weights=early_signal_weights)
    evid = evidence_score(cluster.signals, weights=evidence_weights)
    v_status = verification_status(cluster.signals)
    repo.apply_scores(event_id, early.total, evid.total, v_status)

    return created
