"""The event assembly pipeline.

Coordinates clustering of geocoded signals into story clusters, matching against
candidate events, creating or attaching to events, recording observations, and
applying dual scores.

This module imports neither SQLAlchemy nor httpx.
"""

from collections.abc import Mapping
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from episignal_backend.db.types import RelationshipType
from episignal_backend.events.cluster import build_clusters
from episignal_backend.events.documents import MatchAction
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
) -> AssemblySummary:
    """Run the end-to-end event assembly pass."""
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
            for sig in cluster.signals:
                repo.attach_signal(
                    event_id,
                    sig.signal_id,
                    relationship_type=RelationshipType.SUPPORTING_SOURCE,
                    match_score=match_score,
                    is_primary=False,
                )
                repo.record_observation(event_id, sig)
                repo.add_locations(event_id, sig.locations)
                repo.mark_matched(sig.signal_id)
                signals_attached += 1

            # Recompute scores on target event
            early = early_signal_score(cluster.signals, now=now, weights=early_signal_weights)
            evid = evidence_score(cluster.signals, weights=evidence_weights)
            v_status = verification_status(cluster.signals)
            repo.apply_scores(event_id, early.total, evid.total, v_status)

        elif decision.action is MatchAction.CREATE:
            created = repo.create_event(cluster)
            events_created += 1
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
                signals_attached += 1

            # Compute scores on created event
            early = early_signal_score(cluster.signals, now=now, weights=early_signal_weights)
            evid = evidence_score(cluster.signals, weights=evidence_weights)
            v_status = verification_status(cluster.signals)
            repo.apply_scores(event_id, early.total, evid.total, v_status)

        elif decision.action is MatchAction.REFUSE:
            for sig in cluster.signals:
                repo.mark_needs_review(sig.signal_id)
                signals_refused += 1

    for sig in unclusterable:
        repo.mark_needs_review(sig.signal_id)

    repo.commit()

    return AssemblySummary(
        signals_seen=len(signals),
        clusters_built=len(clusters),
        events_created=events_created,
        signals_attached=signals_attached,
        signals_refused=signals_refused,
        unclusterable=len(unclusterable),
    )
