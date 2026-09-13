"""The event assembly pipeline.

Coordinates clustering of extracted signals into story clusters, matching against
candidate events, creating or attaching to events, recording observations, and
applying dual scores.

This module imports neither SQLAlchemy nor httpx.
"""

import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from episignal_backend.ai.documents import ModelSpec
from episignal_backend.ai.protocol import ChatModel
from episignal_backend.ai.schema import BriefPoint
from episignal_backend.db.types import Precision, RelationshipType
from episignal_backend.events.cluster import build_clusters
from episignal_backend.events.documents import (
    CandidateEvent,
    LocationForMatching,
    MatchAction,
    SignalForMatching,
    StoryCluster,
    normalize_disease_text,
)
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
from episignal_backend.geocode.normalize import normalized_form
from episignal_backend.ingestion.story import StoryArticle, group_stories

logger = logging.getLogger(__name__)


class AssemblySummary(BaseModel):
    """Counts produced by a run of the event assembly pipeline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signals_seen: int
    clusters_built: int
    story_groups_built: int = 0
    events_created: int
    signals_attached: int
    signals_refused: int
    unclusterable: int
    deltas_applied: int = 0
    ambiguous_judged: int = 0
    ambiguous_attached: int = 0
    touched_event_ids: tuple[UUID, ...] = ()


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
    """Legacy delta seam retained for historical callers; never active."""
    del repo, delta_model, delta_spec, followup_window_days, event_id, chosen
    del previous_brief, cluster, now
    return 0


def run_event_assembly(
    repo: EventRepository,
    *,
    limit: int = 100,
    stale: bool = False,
    cluster_window_days: int = 7,
    cluster_distance_km: float = 50.0,
    match_threshold: float = 0.75,
    review_threshold: float | None = None,
    match_weights: Mapping[str, float] = DEFAULT_MATCH_WEIGHTS,
    match_recency_days: float = 90.0,
    match_distance_km: float = 50.0,
    candidate_lookback_days: int = 7,
    candidate_limit: int = 20,
    early_signal_weights: Mapping[str, float] = DEFAULT_EARLY_SIGNAL_WEIGHTS,
    evidence_weights: Mapping[str, float] = DEFAULT_EVIDENCE_WEIGHTS,
    now: datetime | None = None,
    delta_model: ChatModel | None = None,
    delta_spec: ModelSpec | None = None,
    followup_window_days: float | None = None,
    signal_ids: Sequence[UUID] | None = None,
    story_group_ids: Sequence[Sequence[UUID]] | None = None,
) -> AssemblySummary:
    """Run the end-to-end event assembly pass.

    When `delta_model` and `delta_spec` are given, an attach to an event whose
    latest report is older than `followup_window_days` runs the delta pass and
    writes what changed onto the newest observation. The pass enriches; it
    never gates the attach, and a pass that cannot run changes nothing.

    Ambiguous, refused, and incomplete matches create new events. Matching
    never waits for a model or a human decision.
    """
    if signal_ids is None:
        signals = repo.signals_to_match(limit=limit, stale=stale)
    else:
        signals = repo.signals_to_match(limit=limit, stale=stale, signal_ids=signal_ids)
    if not signals:
        repo.commit()
        return AssemblySummary(
            signals_seen=0,
            clusters_built=0,
            story_groups_built=0,
            events_created=0,
            signals_attached=0,
            signals_refused=0,
            unclusterable=0,
            touched_event_ids=(),
        )

    story_units = _story_units(signals, story_group_ids)
    clusters, unclusterable = _event_clusters(
        story_units,
        window_days=cluster_window_days,
        distance_km=cluster_distance_km,
    )

    events_created = 0
    signals_attached = 0
    signals_refused = 0
    deltas_applied = 0
    ambiguous_judged = 0
    ambiguous_attached = 0
    touched_event_ids: list[UUID] = []

    for cluster in clusters:
        candidates = repo.candidate_events(
            cluster,
            lookback_days=candidate_lookback_days,
            limit=candidate_limit,
            distance_km=match_distance_km,
        )
        decision = decide(
            cluster,
            candidates,
            threshold=match_threshold,
            review_threshold=review_threshold,
            weights=match_weights,
            distance_km=match_distance_km,
            recency_days=match_recency_days,
        )

        for candidate in candidates:
            rejection = decision.candidate_rejections[candidate.event_id]
            logger.info(
                "event match candidate event_id=%s score=%s reason=%s",
                candidate.event_id,
                decision.candidate_scores[candidate.event_id],
                rejection.value if rejection is not None else None,
            )

        if decision.action is MatchAction.ATTACH:
            assert decision.event_id is not None
            event_id = decision.event_id
            if event_id not in touched_event_ids:
                touched_event_ids.append(event_id)
            match_score = decision.match_score if decision.match_score is not None else 1.0
            chosen = next((cand for cand in candidates if cand.event_id == event_id), None)
            previous_brief = repo.latest_brief(event_id)
            logger.info(
                "matched event event_id=%s score=%s",
                event_id,
                match_score,
            )

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

        elif decision.action is MatchAction.AMBIGUOUS:
            created = finalize_event_creation(
                repo,
                cluster=cluster,
                early_signal_weights=early_signal_weights,
                evidence_weights=evidence_weights,
                now=now,
            )
            logger.info("ambiguous match; created new event event_id=%s", created.event_id)
            events_created += 1
            touched_event_ids.append(created.event_id)
            signals_attached += len(cluster.signals)

        elif decision.action is MatchAction.CREATE:
            created = finalize_event_creation(
                repo,
                cluster=cluster,
                early_signal_weights=early_signal_weights,
                evidence_weights=evidence_weights,
                now=now,
            )
            logger.info("created event event_id=%s", created.event_id)
            events_created += 1
            touched_event_ids.append(created.event_id)
            signals_attached += len(cluster.signals)

        elif decision.action is MatchAction.REFUSE:
            created = finalize_event_creation(
                repo,
                cluster=cluster,
                early_signal_weights=early_signal_weights,
                evidence_weights=evidence_weights,
                now=now,
            )
            logger.info("multiple matches; created new event event_id=%s", created.event_id)
            events_created += 1
            touched_event_ids.append(created.event_id)
            signals_attached += len(cluster.signals)

    for cluster in unclusterable:
        created = finalize_event_creation(
            repo,
            cluster=cluster,
            early_signal_weights=early_signal_weights,
            evidence_weights=evidence_weights,
            now=now,
        )
        logger.info("uncertain event fields; created new event event_id=%s", created.event_id)
        events_created += 1
        touched_event_ids.append(created.event_id)
        signals_attached += len(cluster.signals)

    repo.commit()

    return AssemblySummary(
        signals_seen=len(signals),
        clusters_built=len(clusters),
        story_groups_built=len(story_units),
        events_created=events_created,
        signals_attached=signals_attached,
        signals_refused=signals_refused,
        unclusterable=len(unclusterable),
        deltas_applied=deltas_applied,
        ambiguous_judged=ambiguous_judged,
        ambiguous_attached=ambiguous_attached,
        touched_event_ids=tuple(dict.fromkeys(touched_event_ids)),
    )


def _story_units(
    signals: Sequence[SignalForMatching],
    story_group_ids: Sequence[Sequence[UUID]] | None,
) -> tuple[tuple[SignalForMatching, ...], ...]:
    """Build article groups, or consume groups prepared by the scheduler."""
    by_id = {signal.signal_id: signal for signal in signals}
    if story_group_ids is None:
        groups = group_stories(
            tuple(
                StoryArticle(
                    signal_id=signal.signal_id,
                    title=signal.title or "untitled",
                    raw_text=signal.raw_text,
                    published_at=signal.published_at,
                    first_seen_at=signal.first_seen_at,
                )
                for signal in signals
            )
        )
        return tuple(
            tuple(by_id[article.signal_id] for article in group.articles) for group in groups
        )

    assigned: set[UUID] = set()
    units: list[tuple[SignalForMatching, ...]] = []
    for ids in story_group_ids:
        unit_members: list[SignalForMatching] = []
        seen_in_unit: set[UUID] = set()
        for signal_id in ids:
            if signal_id in by_id and signal_id not in assigned and signal_id not in seen_in_unit:
                unit_members.append(by_id[signal_id])
                seen_in_unit.add(signal_id)
        unit = tuple(
            sorted(
                unit_members,
                key=lambda signal: (
                    signal.published_at or signal.first_seen_at,
                    signal.signal_id.bytes,
                ),
            )
        )
        if unit:
            units.append(unit)
            assigned.update(signal.signal_id for signal in unit)
    units.extend(
        (signal,)
        for signal in sorted(
            (signal for signal in signals if signal.signal_id not in assigned),
            key=lambda item: (item.published_at or item.first_seen_at, item.signal_id.bytes),
        )
    )
    return tuple(units)


def _event_clusters(
    story_units: Sequence[tuple[SignalForMatching, ...]],
    *,
    window_days: int,
    distance_km: float,
) -> tuple[tuple[StoryCluster, ...], tuple[StoryCluster, ...]]:
    """Match story units strictly, preserving each unit's source members."""
    representatives = tuple(_event_representative(unit) for unit in story_units)
    strict_clusters, unclusterable = build_clusters(
        representatives,
        window_days=window_days,
        distance_km=distance_km,
    )
    unit_by_representative = {unit[0].signal_id: unit for unit in story_units}
    expanded: list[StoryCluster] = []
    for cluster in strict_clusters:
        members = tuple(
            signal
            for representative in cluster.signals
            for signal in unit_by_representative[representative.signal_id]
        )
        expanded.append(
            StoryCluster(
                signals=members,
                event_representative=_event_representative(cluster.signals),
            )
        )
    expanded.sort(key=lambda cluster: (cluster.span[0], cluster.signals[0].signal_id.bytes))
    return tuple(expanded), tuple(
        StoryCluster(
            signals=unit_by_representative[representative.signal_id],
            event_representative=representative,
        )
        for representative in unclusterable
    )


_UNRESOLVED_DISEASE_TEXTS = frozenset(
    {
        "disease",
        "generic",
        "generic disease",
        "infectious disease",
        "unknown",
        "unknown disease",
        "unspecified",
        "unspecified disease",
    }
)

_LOCATION_PRECISION_RANK = {
    Precision.PLACE: 4,
    Precision.ADMIN2: 3,
    Precision.ADMIN1: 2,
    Precision.COUNTRY: 1,
    Precision.UNRESOLVED: 0,
}


def _resolved_disease_identity(signal: SignalForMatching) -> str | None:
    if signal.disease_id is not None:
        return f"id:{signal.disease_id}"
    disease_text = normalize_disease_text(signal.disease_text)
    if disease_text is None or disease_text in _UNRESOLVED_DISEASE_TEXTS:
        return None
    return f"text:{disease_text}"


def _disease_consensus(unit: tuple[SignalForMatching, ...]) -> tuple[UUID | None, str | None]:
    identities = [
        (identity, signal)
        for signal in unit
        if (identity := _resolved_disease_identity(signal)) is not None
    ]
    if not identities:
        return None, None

    counts = Counter(identity for identity, _ in identities)
    winner, winner_count = counts.most_common(1)[0]
    if len(counts) > 1 and winner_count * 2 <= len(identities):
        return None, None

    winning_signal = next(signal for identity, signal in identities if identity == winner)
    return winning_signal.disease_id, winning_signal.disease_text


def _location_identity(location: LocationForMatching) -> tuple[str, str, str, str]:
    return (
        (location.country_code or "").strip().upper(),
        normalized_form(location.admin1) if location.admin1 else "",
        normalized_form(location.admin2) if location.admin2 else "",
        normalized_form(location.place_name) if location.place_name else "",
    )


def _resolved_location_consensus(
    unit: tuple[SignalForMatching, ...],
) -> tuple[LocationForMatching, ...]:
    resolved = tuple(
        location
        for signal in unit
        for location in signal.locations
        if location.precision != Precision.UNRESOLVED
        and location.country_code is not None
        and location.country_code.strip()
    )
    if not resolved:
        return ()

    identities = {_location_identity(location) for location in resolved}
    if len(identities) != 1:
        return ()

    chosen = max(
        resolved,
        key=lambda location: (
            location.location_role.value == "primary",
            _LOCATION_PRECISION_RANK[location.precision],
        ),
    )
    return (chosen,)


def _event_representative(unit: tuple[SignalForMatching, ...]) -> SignalForMatching:
    """Build a conservative epidemiologic identity for one story unit."""
    lead = unit[0]
    disease_id, disease_text = _disease_consensus(unit)
    locations = _resolved_location_consensus(unit)
    embedding = next((signal.embedding for signal in unit if signal.embedding is not None), None)
    return lead.model_copy(
        update={
            "disease_id": disease_id,
            "disease_text": disease_text,
            "locations": locations,
            "embedding": embedding,
        }
    )
