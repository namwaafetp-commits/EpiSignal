"""The storage boundary for story clustering, event matching, and scoring.

The only module in `events/` that imports SQLAlchemy, and the only one that
owns transactions.

Maps between ORM models and pure domain contracts across the boundary.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from geoalchemy2.elements import WKTElement
from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.orm import Session

from episignal_backend.ai.schema import Extraction
from episignal_backend.db.types import (
    EventStatus,
    EventType,
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
    EventObservation,
    EventSignal,
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
            extraction = None
            if sig.ai_extraction is not None:
                try:
                    extraction = Extraction.model_validate(sig.ai_extraction)
                except Exception:
                    if isinstance(sig.ai_extraction, dict):
                        payload = dict(sig.ai_extraction)
                        payload.setdefault("confidence", 0.5)
                        try:
                            extraction = Extraction.model_validate(payload)
                        except Exception:
                            extraction = None
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
        if cluster.disease_id is None:
            raise ValueError("Cannot create an event for a cluster without a disease_id")

        event_id = uuid4()
        public_id = f"EVT-{event_id.hex[:8].upper()}"
        slug = f"event-{event_id.hex[:10].lower()}"

        rep_loc = cluster.representative_location
        country_code = rep_loc.country_code if rep_loc else None
        admin1 = rep_loc.admin1 if rep_loc else None
        admin2 = rep_loc.admin2 if rep_loc else None
        place_name = rep_loc.place_name if rep_loc else None
        lat = rep_loc.latitude if rep_loc else None
        lon = rep_loc.longitude if rep_loc else None
        geom = (
            WKTElement(f"POINT({lon} {lat})", srid=4326)
            if (lat is not None and lon is not None)
            else None
        )

        loc_label = place_name or admin1 or country_code or "Unknown"
        title = f"Outbreak event in {loc_label} ({public_id})"

        first_sig_at = cluster.span[0]
        event_start_date = first_sig_at.date()
        last_updated_at = cluster.span[1]

        event = Event(
            id=event_id,
            public_id=public_id,
            slug=slug,
            title=title,
            disease_id=cluster.disease_id,
            pathogen_id=None,
            event_type=EventType.OUTBREAK,
            status=EventStatus.MONITORING,
            verification_status=VerificationStatus.SIGNAL,
            country_code=country_code,
            admin1=admin1,
            admin2=admin2,
            latitude=lat,
            longitude=lon,
            geometry=geom,
            first_signal_at=first_sig_at,
            event_start_date=event_start_date,
            last_updated_at=last_updated_at,
        )
        self._session.add(event)

        locations = (rep_loc,) if rep_loc is not None else ()
        return CandidateEvent(
            event_id=event_id,
            disease_id=cluster.disease_id,
            locations=locations,
            first_signal_at=first_sig_at,
            last_updated_at=last_updated_at,
        )

    def attach_signal(
        self,
        event_id: UUID,
        signal_id: UUID,
        *,
        relationship_type: RelationshipType,
        match_score: float,
        is_primary: bool,
    ) -> None:
        rel = EventSignal(
            event_id=event_id,
            signal_id=signal_id,
            relationship_type=relationship_type,
            match_score=match_score,
            is_primary=is_primary,
        )
        self._session.add(rel)

    def record_observation(self, event_id: UUID, signal: SignalForMatching) -> None:
        obs_date = None
        conf = None
        notes = None
        suspected = None
        probable = None
        confirmed = None
        total = None
        new_cases = None
        deaths = None
        new_deaths = None
        recoveries = None
        hospitalizations = None
        cfr = None
        affected_admin_areas = None

        if signal.extraction is not None:
            conf = signal.extraction.confidence
            notes = (
                "\n".join(point.text for point in signal.extraction.brief)
                if signal.extraction.brief
                else None
            )
            if signal.extraction.dates:
                obs_date = signal.extraction.dates.event_date or signal.extraction.dates.data_as_of
            if signal.extraction.epidemiology:
                epi = signal.extraction.epidemiology
                if epi.suspected_cases is not None:
                    suspected = epi.suspected_cases.value
                if epi.confirmed_cases is not None:
                    confirmed = epi.confirmed_cases.value
                if epi.total_cases is not None:
                    total = epi.total_cases.value
                if epi.new_cases is not None:
                    new_cases = epi.new_cases.value
                if epi.deaths is not None:
                    deaths = epi.deaths.value
                if epi.new_deaths is not None:
                    new_deaths = epi.new_deaths.value

        rep_at = signal.published_at if signal.published_at is not None else signal.first_seen_at
        if obs_date is None and rep_at is not None:
            obs_date = rep_at.date()

        obs = EventObservation(
            id=uuid4(),
            event_id=event_id,
            signal_id=signal.signal_id,
            observation_date=obs_date,
            reported_at=rep_at,
            suspected_cases=suspected,
            probable_cases=probable,
            confirmed_cases=confirmed,
            total_cases=total,
            new_cases=new_cases,
            deaths=deaths,
            new_deaths=new_deaths,
            recoveries=recoveries,
            hospitalizations=hospitalizations,
            cfr=cfr,
            affected_admin_areas=affected_admin_areas,
            notes=notes,
            extraction_confidence=conf,
        )
        self._session.add(obs)

    def add_locations(self, event_id: UUID, locations: Sequence[LocationForMatching]) -> None:
        for loc in locations:
            geom = (
                WKTElement(f"POINT({loc.longitude} {loc.latitude})", srid=4326)
                if (loc.latitude is not None and loc.longitude is not None)
                else None
            )
            event_loc = EventLocation(
                id=uuid4(),
                event_id=event_id,
                location_role=loc.location_role,
                country_code=loc.country_code,
                admin1=loc.admin1,
                admin2=loc.admin2,
                place_name=loc.place_name,
                latitude=loc.latitude,
                longitude=loc.longitude,
                geometry=geom,
            )
            self._session.add(event_loc)

    def apply_scores(
        self,
        event_id: UUID,
        early_signal_score: float,
        evidence_score: float,
        verification_status: VerificationStatus,
    ) -> None:
        self._session.execute(
            update(Event)
            .where(Event.id == event_id)
            .values(
                early_signal_score=early_signal_score,
                evidence_score=evidence_score,
                verification_status=verification_status,
                last_updated_at=datetime.now(UTC),
            )
        )

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
