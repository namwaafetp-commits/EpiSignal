"""Candidate match scoring and the conservative matching decision.

Pure functions for scoring how well a story cluster matches candidate events
and deciding whether to attach or create.

This module imports neither SQLAlchemy nor httpx.
"""

from collections.abc import Mapping, Sequence
from uuid import UUID

from episignal_backend.db.types import LocationRole, Precision
from episignal_backend.events.cluster import (
    precision_weight,
    spatially_compatible,
)
from episignal_backend.events.documents import (
    CandidateEvent,
    LocationForMatching,
    MatchAction,
    MatchDecision,
    MatchRejection,
    StoryCluster,
)
from episignal_backend.geocode.normalize import normalized_form

DEFAULT_MATCH_WEIGHTS: dict[str, float] = {
    "disease": 0.30,
    "spatial": 0.35,
    "temporal": 0.20,
    "precision": 0.15,
}

_PRECISION_RANK: dict[Precision, int] = {
    Precision.PLACE: 4,
    Precision.ADMIN2: 3,
    Precision.ADMIN1: 2,
    Precision.COUNTRY: 1,
    Precision.UNRESOLVED: 0,
}


def _candidate_representative_location(
    candidate: CandidateEvent,
) -> LocationForMatching | None:
    if not candidate.locations:
        return None
    primary_locs = [loc for loc in candidate.locations if loc.location_role == LocationRole.PRIMARY]
    candidates = primary_locs if primary_locs else list(candidate.locations)
    return max(candidates, key=lambda loc: _PRECISION_RANK.get(loc.precision, -1))


def _disease_identity(value: object) -> str | None:
    identity = getattr(value, "disease_identity", None)
    if isinstance(identity, str):
        return identity
    disease_id = getattr(value, "disease_id", None)
    if disease_id is not None:
        return f"id:{disease_id}"
    disease_text = getattr(value, "disease_text", None)
    normalized = normalized_form(disease_text) if isinstance(disease_text, str) else ""
    return f"text:{normalized}" if normalized else None


def match_score(
    cluster: StoryCluster,
    candidate: CandidateEvent,
    *,
    weights: Mapping[str, float] = DEFAULT_MATCH_WEIGHTS,
    distance_km: float = 50.0,
    recency_days: float = 90.0,
) -> float:
    """Score how well a story cluster matches an existing candidate event in 0-1.

    Components:
    - disease: 1.0 if identical disease, else 0.0.
    - spatial: agreement at coarsest shared precision, in 0.0-1.0.
    - temporal: recency overlap against candidate span in 0.0-1.0.
    - precision: specificity weight of cluster's location in 0.0-1.0.

    If disease or spatial agreement is zero, the total match score is zero.
    """
    # 1. Disease component
    cluster_identity = _disease_identity(cluster)
    if cluster_identity is None or cluster_identity != _disease_identity(candidate):
        return 0.0
    disease_score = 1.0

    # 2. Spatial component
    loc_c = cluster.representative_location
    loc_cand = _candidate_representative_location(candidate)
    if loc_c is None or loc_cand is None:
        return 0.0
    overlapping = [
        (left, right)
        for left in (loc for sig in cluster.signals for loc in sig.locations)
        for right in candidate.locations
        if spatially_compatible(left, right, distance_km=distance_km)
    ]
    if not overlapping:
        return 0.0
    spatial_score = (
        0.75
        if any(left.place_name or left.admin2 or left.admin1 for left, _ in overlapping)
        else 1.0
    )

    # 3. Temporal component
    c_start, c_end = cluster.span
    cand_start = candidate.first_signal_at
    cand_end = candidate.last_updated_at

    if c_end < cand_start:
        gap = (cand_start - c_end).total_seconds() / 86400.0
    elif c_start > cand_end:
        gap = (c_start - cand_end).total_seconds() / 86400.0
    else:
        gap = 0.0

    temporal_score = max(0.0, 1.0 - gap / recency_days)

    # 4. Precision component
    prec_score = precision_weight(loc_c.precision)

    # Assert all components are in [0, 1] before weighting
    assert 0.0 <= disease_score <= 1.0
    assert 0.0 <= spatial_score <= 1.0
    assert 0.0 <= temporal_score <= 1.0
    assert 0.0 <= prec_score <= 1.0

    w_d = weights.get("disease", 0.30)
    w_s = weights.get("spatial", 0.35)
    w_t = weights.get("temporal", 0.20)
    w_p = weights.get("precision", 0.15)

    total = w_d * disease_score + w_s * spatial_score + w_t * temporal_score + w_p * prec_score
    return max(0.0, min(1.0, total))


def _temporal_gap_days(cluster: StoryCluster, candidate: CandidateEvent) -> float:
    cluster_start, cluster_end = cluster.span
    if cluster_end < candidate.first_signal_at:
        return (candidate.first_signal_at - cluster_end).total_seconds() / 86400.0
    if cluster_start > candidate.last_updated_at:
        return (cluster_start - candidate.last_updated_at).total_seconds() / 86400.0
    return 0.0


def _deterministic_rejection(
    cluster: StoryCluster,
    candidate: CandidateEvent,
    *,
    distance_km: float,
    recency_days: float,
) -> MatchRejection | None:
    cluster_identity = _disease_identity(cluster)
    if cluster_identity is None or cluster_identity != _disease_identity(candidate):
        return MatchRejection.DISEASE_MISMATCH

    cluster_location = cluster.representative_location
    candidate_location = _candidate_representative_location(candidate)
    if _temporal_gap_days(cluster, candidate) > recency_days:
        return MatchRejection.OUTSIDE_TIME_WINDOW

    if (
        cluster_location is None
        or candidate_location is None
        or not any(
            spatially_compatible(left, right, distance_km=distance_km)
            for signal in cluster.signals
            for left in signal.locations
            for right in candidate.locations
        )
    ):
        return MatchRejection.TOO_FAR

    return None


def decide(
    cluster: StoryCluster,
    candidates: Sequence[CandidateEvent],
    *,
    threshold: float = 0.75,
    review_threshold: float | None = None,
    weights: Mapping[str, float] = DEFAULT_MATCH_WEIGHTS,
    distance_km: float = 50.0,
    recency_days: float = 90.0,
) -> MatchDecision:
    """Make the conservative matching decision for a story cluster.

    - attach: exactly one candidate event scores >= threshold.
    - create: no candidate event scores >= threshold.
    - ambiguous: a single candidate scores between the optional legacy review
      threshold and the auto threshold; the caller creates a new event.
    - refuse: two or more candidate events score >= threshold; the caller
      creates a new event.

    Deterministic guards are the complete matching boundary; no semantic
    similarity or model judgement is consulted.
    """
    candidate_scores: dict[UUID, float] = {}
    candidate_rejections: dict[UUID, MatchRejection | None] = {}
    qualifiers: list[tuple[CandidateEvent, float]] = []
    ambiguous: list[tuple[CandidateEvent, float]] = []

    for cand in candidates:
        # These guards are the safety boundary: a semantic resemblance must
        # never revive a different disease, place, or time window.
        rejection = _deterministic_rejection(
            cluster,
            cand,
            distance_km=distance_km,
            recency_days=recency_days,
        )
        if rejection is not None:
            candidate_scores[cand.event_id] = 0.0
            candidate_rejections[cand.event_id] = rejection
            continue

        score = match_score(
            cluster,
            cand,
            weights=weights,
            distance_km=distance_km,
            recency_days=recency_days,
        )
        candidate_scores[cand.event_id] = score
        if score >= threshold:
            qualifiers.append((cand, score))
            candidate_rejections[cand.event_id] = None
        elif review_threshold is not None and score >= review_threshold:
            ambiguous.append((cand, score))
            candidate_rejections[cand.event_id] = None
        else:
            candidate_rejections[cand.event_id] = MatchRejection.SCORE_BELOW_THRESHOLD

    if len(qualifiers) == 1:
        chosen_cand, chosen_score = qualifiers[0]
        return MatchDecision(
            action=MatchAction.ATTACH,
            event_id=chosen_cand.event_id,
            match_score=chosen_score,
            candidate_scores=candidate_scores,
            candidate_rejections=candidate_rejections,
        )
    elif len(qualifiers) >= 2:
        return MatchDecision(
            action=MatchAction.REFUSE,
            candidate_scores=candidate_scores,
            candidate_rejections=candidate_rejections,
        )
    elif len(ambiguous) == 1:
        chosen_cand, chosen_score = ambiguous[0]
        return MatchDecision(
            action=MatchAction.AMBIGUOUS,
            event_id=chosen_cand.event_id,
            match_score=chosen_score,
            candidate_scores=candidate_scores,
            candidate_rejections=candidate_rejections,
        )
    else:
        return MatchDecision(
            action=MatchAction.CREATE,
            candidate_scores=candidate_scores,
            candidate_rejections=candidate_rejections,
        )
