"""The storage boundary for story clustering, event matching, and scoring.

The only module in `events/` that imports SQLAlchemy, and the only one that
owns transactions.

Maps between ORM models and pure domain contracts across the boundary.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.orm import Session

from episignal_backend.ai.schema import Extraction
from episignal_backend.db.types import (
    Precision,
    ProcessingStatus,
    RelationshipType,
    VerificationStatus,
)
from episignal_backend.events.documents import (
    CandidateEvent,
    LocationForMatching,
    SignalForMatching,
    StoryCluster,
)
from episignal_backend.models import (
    Event,
    EventLocation,
    Signal,
    SignalLocation,
    Source,
)


def _infer_precision(loc: Any) -> Precision:
    prec = getattr(loc, "precision", None)
    if isinstance(prec, Precision):
        return prec
    if getattr(loc, "place_name", None):
        return Precision.PLACE
    if getattr(loc, "admin2", None):
        return Precision.ADMIN2
    if getattr(loc, "admin1", None):
        return Precision.ADMIN1
    if getattr(loc, "country_code", None):
        return Precision.COUNTRY
    return Precision.UNRESOLVED


class SqlAlchemyEventRepository:
    """SQLAlchemy implementation of the EventRepository storage protocol."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def signals_to_match(self, limit: int, *, stale: bool = False) -> Sequence[SignalForMatching]:
        """Select signals awaiting matching or already matched when stale=True."""
        status_filter: ColumnElement[bool]
        if stale:
            status_filter = Signal.processing_status.in_(
                [ProcessingStatus.GEOCODED, ProcessingStatus.MATCHED]
            )
        else:
            status_filter = Signal.processing_status == ProcessingStatus.GEOCODED

        query = (
            select(Signal, Source.is_official, Source.credibility_tier)
            .join(Source, Signal.source_id == Source.id)
            .where(status_filter)
            .order_by(Signal.first_seen_at.asc(), Signal.id.asc())
            .limit(limit)
        )

        rows = self._session.execute(query).all()
        if not rows:
            return ()

        signal_ids = [sig.id for sig, _, _ in rows]

        loc_query = select(SignalLocation).where(SignalLocation.signal_id.in_(signal_ids))
        loc_rows = self._session.execute(loc_query).scalars().all()

        locs_by_signal: dict[UUID, list[LocationForMatching]] = defaultdict(list)
        for loc in loc_rows:
            locs_by_signal[loc.signal_id].append(
                LocationForMatching(
                    location_role=loc.location_role,
                    precision=loc.precision,
                    country_code=loc.country_code,
                    admin1=loc.admin1,
                    admin2=loc.admin2,
                    place_name=loc.place_name,
                    latitude=loc.latitude,
                    longitude=loc.longitude,
                )
            )

        signals: list[SignalForMatching] = []
        for sig, is_official, cred_tier in rows:
            extraction = (
                Extraction.model_validate(sig.ai_extraction)
                if sig.ai_extraction is not None
                else None
            )
            signals.append(
                SignalForMatching(
                    signal_id=sig.id,
                    disease_id=sig.disease_id,
                    source_id=sig.source_id,
                    source_is_official=is_official,
                    credibility_tier=cred_tier,
                    published_at=sig.published_at,
                    first_seen_at=sig.first_seen_at,
                    locations=tuple(locs_by_signal.get(sig.id, ())),
                    extraction=extraction,
                )
            )

        return tuple(signals)

    def candidate_events(
        self,
        cluster: StoryCluster,
        *,
        recency_days: float = 90.0,
        distance_km: float = 50.0,
    ) -> Sequence[CandidateEvent]:
        if cluster.disease_id is None:
            return ()

        rep_loc = cluster.representative_location
        if rep_loc is None or rep_loc.country_code is None:
            return ()

        cutoff = cluster.span[0] - timedelta(days=recency_days)

        conditions: list[ColumnElement[bool]] = [
            Event.disease_id == cluster.disease_id,
            Event.last_updated_at >= cutoff,
        ]

        if (
            rep_loc.precision in (Precision.PLACE, Precision.ADMIN2)
            and rep_loc.latitude is not None
            and rep_loc.longitude is not None
        ):
            ref_point = func.ST_SetSRID(
                func.ST_MakePoint(rep_loc.longitude, rep_loc.latitude), 4326
            )
            conditions.append(func.ST_DWithin(Event.geometry, ref_point, distance_km * 1000.0))
        else:
            conditions.append(Event.country_code == rep_loc.country_code)

        event_query = select(Event).where(*conditions)
        events = self._session.execute(event_query).scalars().all()
        if not events:
            return ()

        event_ids = [ev.id for ev in events]
        loc_query = select(EventLocation).where(EventLocation.event_id.in_(event_ids))
        loc_rows = self._session.execute(loc_query).scalars().all()

        locs_by_event: dict[UUID, list[LocationForMatching]] = defaultdict(list)
        for loc in loc_rows:
            locs_by_event[loc.event_id].append(
                LocationForMatching(
                    location_role=loc.location_role,
                    precision=_infer_precision(loc),
                    country_code=loc.country_code,
                    admin1=loc.admin1,
                    admin2=loc.admin2,
                    place_name=loc.place_name,
                    latitude=loc.latitude,
                    longitude=loc.longitude,
                )
            )

        candidates: list[CandidateEvent] = []
        for ev in events:
            assert ev.disease_id is not None
            first_sig: datetime = (
                ev.first_signal_at
                if ev.first_signal_at is not None
                else (ev.created_at if ev.created_at is not None else datetime.now(UTC))
            )
            candidates.append(
                CandidateEvent(
                    event_id=ev.id,
                    disease_id=ev.disease_id,
                    locations=tuple(locs_by_event.get(ev.id, ())),
                    first_signal_at=first_sig,
                    last_updated_at=ev.last_updated_at,
                )
            )

        return tuple(candidates)

    def create_event(self, cluster: StoryCluster) -> CandidateEvent:
        raise NotImplementedError

    def attach_signal(
        self,
        event_id: UUID,
        signal_id: UUID,
        *,
        relationship_type: RelationshipType,
        match_score: float,
        is_primary: bool,
    ) -> None:
        raise NotImplementedError

    def record_observation(self, event_id: UUID, signal: SignalForMatching) -> None:
        raise NotImplementedError

    def add_locations(self, event_id: UUID, locations: Sequence[LocationForMatching]) -> None:
        raise NotImplementedError

    def apply_scores(
        self,
        event_id: UUID,
        early_signal_score: float,
        evidence_score: float,
        verification_status: VerificationStatus,
    ) -> None:
        raise NotImplementedError

    def mark_matched(self, signal_id: UUID) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(processing_status=ProcessingStatus.MATCHED)
        )

    def mark_needs_review(self, signal_id: UUID) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(processing_status=ProcessingStatus.NEEDS_REVIEW)
        )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
