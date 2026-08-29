"""The event assembly pipeline.

Coordinates clustering of geocoded signals into story clusters, matching against
candidate events, creating or attaching to events, recording observations, and
applying dual scores.

This module imports neither SQLAlchemy nor httpx.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from episignal_backend.ai.documents import ModelSpec
from episignal_backend.ai.ladder import cost_row
from episignal_backend.ai.protocol import ChatModel
from episignal_backend.ai.schema import BriefPoint
from episignal_backend.db.types import AiPurpose, RelationshipType, ReviewReason
from episignal_backend.events.cluster import build_clusters
from episignal_backend.events.delta import DeltaOutcome, delta_payload, run_delta
from episignal_backend.events.documents import CandidateEvent, MatchAction, StoryCluster
from episignal_backend.events.finalize import (
    finalize_event_creation,
    finalize_event_link,
)
from episignal_backend.events.match import DEFAULT_MATCH_WEIGHTS, decide
from episignal_backend.events.protocol import EventRepository
from episignal_backend.events.score import (
    DEFAULT_EARLY_SIGNAL_WEIGHTS,
    DEFAULT_EVIDENCE_WEIGHTS,
    early_signal_score,
    evidence_score,
    verification_status,
)


class AssemblySummary(BaseModel):
    """Counts produced by a run of the event assembly pipeline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signals_seen: int
    clusters_built: int
    events_created: int
    signals_attached: int
    signals_refused: int
    unclusterable: int
    deltas_applied: int = 0


def _maybe_run_delta(
    repo: EventRepository,
    delta_model: ChatModel | None,
    delta_spec: ModelSpec | None,
    followup_window_days: float | None,
    *,
    event_id: UUID,
    chosen: CandidateEvent | None,
    previous_brief: tuple[BriefPoint, ...] | None,
    cluster: StoryCluster,
    now: datetime | None,
) -> int:
    """Run the delta pass when this attach followed a recent report.

    Returns 1 when a delta landed, 0 otherwise. Every early return is a
    no-op: the attach has already happened and must stand whether or not the
    pass runs, succeeds, or fails.
    """
    if delta_model is None or delta_spec is None or followup_window_days is None:
        return 0
    if chosen is None or previous_brief is None:
        return 0
    reference = now or datetime.now(UTC)
    if reference - chosen.last_updated_at > timedelta(days=followup_window_days):
        return 0
    briefed = [
        sig for sig in cluster.signals if sig.extraction is not None and sig.extraction.brief
    ]
    if not briefed:
        return 0

    # The delta lands on this attach's newest report, so a reader comparing
    # the row with its neighbours sees the change where the change was
    # reported, not on an arbitrary member of the cluster.
    target = max(briefed, key=lambda sig: sig.published_at or sig.first_seen_at)
    target_brief = target.extraction.brief if target.extraction is not None else ()
    result = run_delta(delta_model, delta_spec, previous=previous_brief, new=target_brief)
    if result.attempt is not None:
        repo.record_ai_request(
            cost_row(
                result.attempt,
                purpose=AiPurpose.FOLLOW_UP,
                signal_id=target.signal_id,
                batch_size=1,
                at=reference,
            )
        )
    if result.outcome is DeltaOutcome.ACCEPTED and result.delta is not None:
        repo.apply_delta(event_id, target.signal_id, delta_payload(result.delta))
        return 1
    return 0


def run_event_assembly(
    repo: EventRepository,
    *,
    limit: int = 100,
    stale: bool = False,
    cluster_window_days: int = 7,
    cluster_distance_km: float = 50.0,
    match_threshold: float = 0.6,
    match_weights: Mapping[str, float] = DEFAULT_MATCH_WEIGHTS,
    match_recency_days: float = 90.0,
    match_distance_km: float = 50.0,
    early_signal_weights: Mapping[str, float] = DEFAULT_EARLY_SIGNAL_WEIGHTS,
    evidence_weights: Mapping[str, float] = DEFAULT_EVIDENCE_WEIGHTS,
    now: datetime | None = None,
    delta_model: ChatModel | None = None,
    delta_spec: ModelSpec | None = None,
    followup_window_days: float | None = None,
) -> AssemblySummary:
    """Run the end-to-end event assembly pass.

    When `delta_model` and `delta_spec` are given, an attach to an event whose
    latest report is older than `followup_window_days` runs the delta pass and
    writes what changed onto the newest observation. The pass enriches; it
    never gates the attach, and a pass that cannot run changes nothing.
    """
    signals = repo.signals_to_match(limit=limit, stale=stale)
    if not signals:
        repo.commit()
        return AssemblySummary(
            signals_seen=0,
            clusters_built=0,
            events_created=0,
            signals_attached=0,
            signals_refused=0,
            unclusterable=0,
        )

    clusters, unclusterable = build_clusters(
        signals,
        window_days=cluster_window_days,
        distance_km=cluster_distance_km,
    )

    events_created = 0
    signals_attached = 0
    signals_refused = 0
    deltas_applied = 0

    for cluster in clusters:
        candidates = repo.candidate_events(
            cluster,
            recency_days=match_recency_days,
            distance_km=match_distance_km,
        )
        decision = decide(
            cluster,
            candidates,
            threshold=match_threshold,
            weights=match_weights,
            distance_km=match_distance_km,
            recency_days=match_recency_days,
        )

        if decision.action is MatchAction.ATTACH:
            assert decision.event_id is not None
            event_id = decision.event_id
            match_score = decision.match_score if decision.match_score is not None else 1.0
            chosen = next((cand for cand in candidates if cand.event_id == event_id), None)
            previous_brief = repo.latest_brief(event_id)

            for sig in cluster.signals:
                finalize_event_link(
                    repo,
                    event_id=event_id,
                    signal=sig,
                    relationship_type=RelationshipType.SUPPORTING_SOURCE,
                    match_score=match_score,
                    is_primary=False,
                    early_signal_weights=early_signal_weights,
                    evidence_weights=evidence_weights,
                    now=now,
                )
                signals_attached += 1

            # Recompute cluster-level scores across all attached cluster signals
            early = early_signal_score(cluster.signals, now=now, weights=early_signal_weights)
            evid = evidence_score(cluster.signals, weights=evidence_weights)
            v_status = verification_status(cluster.signals)
            repo.apply_scores(event_id, early.total, evid.total, v_status)

            deltas_applied += _maybe_run_delta(
                repo,
                delta_model,
                delta_spec,
                followup_window_days,
                event_id=event_id,
                chosen=chosen,
                previous_brief=previous_brief,
                cluster=cluster,
                now=now,
            )

        elif decision.action is MatchAction.CREATE:
            finalize_event_creation(
                repo,
                cluster=cluster,
                early_signal_weights=early_signal_weights,
                evidence_weights=evidence_weights,
                now=now,
            )
            events_created += 1
            signals_attached += len(cluster.signals)

        elif decision.action is MatchAction.REFUSE:
            scores_to_snapshot = {
                eid: score
                for eid, score in decision.candidate_scores.items()
                if score >= 0.60
            }
            for sig in cluster.signals:
                repo.open_review(
                    sig.signal_id,
                    reason=ReviewReason.EVENT_MATCH_AMBIGUOUS,
                    candidate_scores=scores_to_snapshot,
                )
                signals_refused += 1

    for sig in unclusterable:
        if sig.disease_id is None:
            reason = ReviewReason.DISEASE_UNRESOLVED
        else:
            reason = ReviewReason.LOCATION_UNRESOLVED
        repo.open_review(sig.signal_id, reason=reason)

    repo.commit()

    return AssemblySummary(
        signals_seen=len(signals),
        clusters_built=len(clusters),
        events_created=events_created,
        signals_attached=signals_attached,
        signals_refused=signals_refused,
        unclusterable=len(unclusterable),
        deltas_applied=deltas_applied,
    )
