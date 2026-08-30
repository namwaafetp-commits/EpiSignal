"""Candidate match scoring and the conservative matching decision.

Pure functions for scoring how well a story cluster matches candidate events
and deciding whether to attach, create, or refuse.

This module imports neither SQLAlchemy nor httpx.
"""

from collections.abc import Callable, Mapping, Sequence
from uuid import UUID

from episignal_backend.db.types import LocationRole, Precision
from episignal_backend.events.cluster import (
    haversine_distance_km,
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

DEFAULT_MATCH_WEIGHTS: dict[str, float] = {
    "disease": 0.30,
    "spatial": 0.35,
    "temporal": 0.20,
    "precision": 0.15,
}

SIMILARITY_WEIGHT = 0.15

SimilarityFor = Callable[[StoryCluster, CandidateEvent], float | None]

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


def _is_country_only(location: LocationForMatching | None) -> bool:
    """Whether a location supplies no administrative or place-level identity."""
    if location is None:
        return False
    return location.precision == Precision.COUNTRY or not any(
        (location.admin1, location.admin2, location.place_name)
    )


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
    if cluster.disease_id is None or cluster.disease_id != candidate.disease_id:
        return 0.0
    disease_score = 1.0

    # 2. Spatial component
    loc_c = cluster.representative_location
    loc_cand = _candidate_representative_location(candidate)

    if loc_c is None or loc_cand is None:
        return 0.0

    if not spatially_compatible(loc_c, loc_cand, distance_km=distance_km):
        return 0.0

    coarsest = min(loc_c.precision, loc_cand.precision, key=lambda p: _PRECISION_RANK[p])
    if coarsest == Precision.PLACE:
        assert loc_c.latitude is not None and loc_c.longitude is not None
        assert loc_cand.latitude is not None and loc_cand.longitude is not None
        d = haversine_distance_km(
            loc_c.latitude, loc_c.longitude, loc_cand.latitude, loc_cand.longitude
        )
        spatial_score = max(0.5, 1.0 - 0.5 * (d / distance_km))
    elif coarsest == Precision.ADMIN2:
        spatial_score = 0.75
    elif coarsest == Precision.ADMIN1:
        spatial_score = 0.50
    elif coarsest == Precision.COUNTRY:
        spatial_score = 0.25
    else:
        spatial_score = 0.0

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
    if cluster.disease_id is None or cluster.disease_id != candidate.disease_id:
        return MatchRejection.DISEASE_MISMATCH

    cluster_location = cluster.representative_location
    candidate_location = _candidate_representative_location(candidate)
    if (
        cluster_location is not None
        and candidate_location is not None
        and cluster_location.admin1 is not None
        and candidate_location.admin1 is not None
        and cluster_location.admin1 != candidate_location.admin1
    ):
        return MatchRejection.CONFLICTING_ADMIN1

    if _temporal_gap_days(cluster, candidate) > recency_days:
        return MatchRejection.OUTSIDE_TIME_WINDOW

    if (
        cluster_location is None
        or candidate_location is None
        or not spatially_compatible(
            cluster_location,
            candidate_location,
            distance_km=distance_km,
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
    similarity_for: SimilarityFor | None = None,
) -> MatchDecision:
    """Make the conservative matching decision for a story cluster.

    - attach: exactly one candidate event scores >= threshold.
    - create: no candidate event scores >= threshold, and none falls in the
      ambiguous band.
    - ambiguous: a single candidate scores between the review threshold and
      the auto threshold, so an LLM judge must decide.
    - refuse: two or more candidate events score >= threshold.

    Deterministic guards run before ``similarity_for``. Similarity therefore
    cannot be consulted for a refused pair and can only add to its score.
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
        similarity = similarity_for(cluster, cand) if similarity_for is not None else None
        if similarity is not None:
            score = min(1.0, score + SIMILARITY_WEIGHT * max(0.0, similarity))
        candidate_scores[cand.event_id] = score
        country_only = _is_country_only(cluster.representative_location) and _is_country_only(
            _candidate_representative_location(cand)
        )
        if score >= threshold and not country_only:
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
