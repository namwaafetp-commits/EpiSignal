"""The storage boundary for story clustering, event matching, and scoring.

The only module in `events/` that imports SQLAlchemy, and the only one that
owns transactions.

Maps between ORM models and pure domain contracts across the boundary.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from geoalchemy2.elements import WKTElement
from pydantic import ValidationError
from sqlalchemy import ColumnElement, func, or_, select, update
from sqlalchemy.orm import Session

from episignal_backend.ai.documents import AiRequestRecord
from episignal_backend.ai.schema import BriefPoint, Extraction, StoredExtractionPayload
from episignal_backend.db.types import (
    EventStatus,
    EventType,
    Precision,
    ProcessingStatus,
    RelationshipType,
    ReviewReason,
    VerificationStatus,
)
from episignal_backend.events.documents import (
    CandidateEvent,
    EventForSummary,
    LocationForMatching,
    SignalForMatching,
    StoryCluster,
    SummarySource,
)
from episignal_backend.models import (
    AiRequest,
    Disease,
    Event,
    EventLocation,
    EventObservation,
    EventSignal,
    EventSummary,
    Signal,
    SignalLocation,
    Source,
)
from episignal_backend.review.repository import SqlAlchemyReviewRepository


def read_stored_extraction(payload: Any) -> Extraction | None:
    """Read `signals.ai_extraction` back, across every version we have written.

    Returns absence rather than raising: a row this system cannot parse is a row
    matching scores without an extraction, which is worse than a crash only if
    it goes unnoticed — and `processing_status` is where it is noticed.
    """
    if not isinstance(payload, dict):
        return None
    try:
        return StoredExtractionPayload.model_validate(payload)
    except ValidationError:
        return None


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
            extraction = read_stored_extraction(sig.ai_extraction)
            signals.append(
                SignalForMatching(
                    signal_id=sig.id,
                    disease_id=sig.disease_id,
                    source_id=sig.source_id,
                    source_is_official=is_official,
                    credibility_tier=cred_tier,
                    published_at=sig.published_at,
                    first_seen_at=sig.first_seen_at,
                    title=sig.title,
                    locations=tuple(locs_by_signal.get(sig.id, ())),
                    extraction=extraction,
                    embedding=tuple(sig.embedding) if sig.embedding is not None else None,
                )
            )

        return tuple(signals)

    def candidate_events(
        self,
        cluster: StoryCluster,
        *,
        lookback_days: int = 7,
        limit: int = 20,
        distance_km: float = 50.0,
    ) -> Sequence[CandidateEvent]:
        if cluster.disease_id is None:
            return ()

        rep_loc = cluster.representative_location
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)

        conditions: list[ColumnElement[bool]] = [
            Event.disease_id == cluster.disease_id,
            Event.last_updated_at >= cutoff,
        ]

        if rep_loc is not None and rep_loc.country_code is not None:
            conditions.append(
                or_(
                    Event.country_code.is_(None),
                    Event.country_code == rep_loc.country_code,
                )
            )

        if (
            rep_loc is not None
            and rep_loc.precision in (Precision.PLACE, Precision.ADMIN2)
            and rep_loc.latitude is not None
            and rep_loc.longitude is not None
        ):
            ref_point = func.ST_SetSRID(
                func.ST_MakePoint(rep_loc.longitude, rep_loc.latitude), 4326
            )
            conditions.append(func.ST_DWithin(Event.geometry, ref_point, distance_km * 1000.0))
        event_query = (
            select(Event).where(*conditions).order_by(Event.last_updated_at.desc()).limit(limit)
        )
        events = self._session.execute(event_query).scalars().all()
        if not events:
            return ()

        event_ids = [ev.id for ev in events]
        loc_query = select(EventLocation).where(EventLocation.event_id.in_(event_ids))
        loc_rows = self._session.execute(loc_query).scalars().all()

        embedding_query = (
            select(EventSignal.event_id, Signal.embedding)
            .join(Signal, Signal.id == EventSignal.signal_id)
            .where(
                EventSignal.event_id.in_(event_ids),
                EventSignal.is_primary.is_(True),
            )
        )
        embedding_rows = self._session.execute(embedding_query).all()
        embeddings_by_event = {
            event_id: tuple(embedding) if embedding is not None else None
            for event_id, embedding in embedding_rows
        }

        titles_by_event = self._recent_source_titles_by_event(event_ids)

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
                    representative_embedding=embeddings_by_event.get(ev.id),
                    title=ev.title,
                    recent_source_titles=titles_by_event.get(ev.id, ()),
                )
            )

        return tuple(candidates)

    def _recent_source_titles_by_event(
        self, event_ids: Sequence[UUID], *, limit: int = 5
    ) -> dict[UUID, tuple[str, ...]]:
        """The newest attached signal titles per event, newest first.

        One query for every candidate event, so a run of twenty candidates is
        not twenty round trips. The judge reads these as an event's recent
        voice: what it has been saying lately, distinct from one headline.
        """
        if not event_ids:
            return {}
        rows = self._session.execute(
            select(
                EventSignal.event_id,
                Signal.title,
                Signal.published_at,
                Signal.first_seen_at,
            )
            .join(Signal, Signal.id == EventSignal.signal_id)
            .where(EventSignal.event_id.in_(event_ids), Signal.title.is_not(None))
            .order_by(
                EventSignal.event_id,
                func.coalesce(Signal.published_at, Signal.first_seen_at).desc(),
                Signal.id.desc(),
            )
        ).all()
        titles: dict[UUID, list[str]] = defaultdict(list)
        for event_id, title, _published_at, _first_seen_at in rows:
            titles[event_id].append(title)
        return {event_id: tuple(items[:limit]) for event_id, items in titles.items()}

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
            representative_embedding=cluster.representative_embedding,
            title=title,
            recent_source_titles=(),
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
        # Idempotency: a stale re-run must not append a second observation for
        # the same (event, signal) pair. The event_signals primary key already
        # blocks a second attach, but the observation write would not, so guard
        # here too. Nothing is ever overwritten; an existing row is left as the
        # first record of that report.
        existing = self._session.execute(
            select(EventObservation.id).where(
                EventObservation.event_id == event_id,
                EventObservation.signal_id == signal.signal_id,
            )
        ).first()
        if existing is not None:
            return

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

    def open_review(
        self,
        signal_id: UUID,
        *,
        reason: ReviewReason,
        candidate_scores: Mapping[UUID, float] | None = None,
    ) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(processing_status=ProcessingStatus.NEEDS_REVIEW)
        )
        SqlAlchemyReviewRepository(self._session).open_review(
            signal_id, reason=reason, candidate_scores=candidate_scores
        )

    def latest_brief(self, event_id: UUID) -> tuple[BriefPoint, ...] | None:
        row = self._session.execute(
            select(EventObservation.signal_id, Signal.ai_extraction)
            .join(Signal, EventObservation.signal_id == Signal.id)
            .where(EventObservation.event_id == event_id)
            # The newest report wins: `reported_at` is the publisher's clock,
            # `created_at` the pipeline's, and an observation with neither is
            # older than one with either.
            .order_by(
                func.coalesce(EventObservation.reported_at, EventObservation.created_at).desc(),
                EventObservation.created_at.desc(),
            )
            .limit(1)
        ).first()
        if row is None:
            return None
        extraction = read_stored_extraction(row.ai_extraction)
        if extraction is None or not extraction.brief:
            return None
        return tuple(extraction.brief)

    def apply_delta(self, event_id: UUID, signal_id: UUID, delta: dict[str, object]) -> None:
        self._session.execute(
            update(EventObservation)
            .where(
                EventObservation.event_id == event_id,
                EventObservation.signal_id == signal_id,
            )
            .values(delta=delta)
        )

    def record_ai_request(self, record: AiRequestRecord) -> None:
        self._session.add(
            AiRequest(
                ai_model_id=record.ai_model_id,
                model_id=record.model_id,
                tier=record.tier,
                purpose=record.purpose,
                signal_id=record.signal_id,
                batch_size=record.batch_size,
                prompt_tokens=record.prompt_tokens,
                completion_tokens=record.completion_tokens,
                latency_ms=record.latency_ms,
                http_status=record.http_status,
                outcome=record.outcome,
                rejection_reason=record.rejection_reason,
                prompt_price_per_million=record.prompt_price_per_million,
                completion_price_per_million=record.completion_price_per_million,
                cost_usd=record.cost_usd,
                requested_at=record.requested_at,
            )
        )

    def events_awaiting_summary(
        self, *, limit: int, max_age_hours: int
    ) -> Sequence[EventForSummary]:
        """Events that may need a new summary, newest update first.

        The candidate set is any event with an attached signal that was never
        summarized, gained new material since its last summary, or whose last
        summary is older than the max age. Material-change detection then makes
        the final per-event decision.
        """
        now = datetime.now(UTC)
        age_cutoff = now - timedelta(hours=max_age_hours)

        event_ids = (
            self._session.execute(
                select(Event.id)
                .join(EventSignal, EventSignal.event_id == Event.id)
                .where(
                    or_(
                        Event.last_summarized_at.is_(None),
                        Event.last_summarized_at < Event.last_updated_at,
                        Event.last_summarized_at < age_cutoff,
                    )
                )
                # EventSignal is a one-to-many join. Group before limiting so
                # the batch size counts events, not attached signals.
                .group_by(Event.id)
                .order_by(func.max(Event.last_updated_at).desc(), Event.id.asc())
                .limit(limit)
            )
            .scalars()
            .all()
        )

        return tuple(self._build_event_for_summary(event_id) for event_id in event_ids)

    def _build_event_for_summary(self, event_id: UUID) -> EventForSummary:
        event = self._session.execute(select(Event).where(Event.id == event_id)).scalar_one()
        disease = None
        if event.disease_id is not None:
            disease = self._session.execute(
                select(Disease.canonical_name).where(Disease.id == event.disease_id)
            ).scalar_one_or_none()

        # The newest summary this event already carries, and its counts snapshot.
        summary_row = self._session.execute(
            select(EventSummary)
            .where(EventSummary.event_id == event_id)
            .order_by(EventSummary.version.desc())
            .limit(1)
        ).scalar_one_or_none()
        previous_counts = (
            dict(summary_row.counts) if summary_row is not None and summary_row.counts else None
        )
        headline = summary_row.headline if summary_row is not None else event.headline
        summary = summary_row.summary if summary_row is not None else event.summary

        # The latest observation, for the counts comparison.
        observation = self._session.execute(
            select(EventObservation)
            .where(EventObservation.event_id == event_id)
            .order_by(
                func.coalesce(EventObservation.reported_at, EventObservation.created_at).desc(),
                EventObservation.created_at.desc(),
            )
            .limit(1)
        ).scalar_one_or_none()
        latest_observation = self._observation_counts(observation)

        # Attached signals, newest first. Signals seen after the last summary
        # are unsummarized; a never-summarized event counts every member.
        member_rows = self._session.execute(
            select(
                EventSignal.signal_id,
                Signal.title,
                Signal.published_at,
                Signal.first_seen_at,
                Source.name,
                Source.is_official,
                Signal.ai_extraction,
            )
            .join(Signal, Signal.id == EventSignal.signal_id)
            .join(Source, Source.id == Signal.source_id)
            .where(EventSignal.event_id == event_id)
            .order_by(Signal.first_seen_at.desc())
        ).all()

        unsummarized = 0
        sources: list[SummarySource] = []
        for (
            signal_id,
            title,
            published_at,
            first_seen_at,
            source_name,
            is_official,
            ai_extraction,
        ) in member_rows:
            if event.last_summarized_at is None or (
                first_seen_at is not None and first_seen_at > event.last_summarized_at
            ):
                unsummarized += 1
            extraction = read_stored_extraction(ai_extraction)
            brief = tuple(extraction.brief) if extraction is not None else ()
            sources.append(
                SummarySource(
                    signal_id=signal_id,
                    title=title,
                    source_name=source_name or "unknown",
                    is_official=is_official,
                    published_at=published_at,
                    brief=brief,
                )
            )

        return EventForSummary(
            event_id=event.id,
            public_id=event.public_id,
            disease=disease or "",
            location=event.admin1 or event.country_code or "",
            headline=headline,
            summary=summary,
            previous_counts=previous_counts,
            latest_observation=latest_observation,
            unsummarized_articles=unsummarized,
            last_summarized_at=event.last_summarized_at,
            sources=tuple(sources),
        )

    def store_summary(
        self,
        *,
        event_id: UUID,
        headline: str,
        summary: str,
        status: str,
        latest_development: str,
        uncertainties: list[str],
        model_id: str,
        source_signal_ids: list[UUID],
        counts: dict[str, object] | None,
        now: datetime | None = None,
    ) -> int:
        moment = now or datetime.now(UTC)
        version_row = self._session.execute(
            select(func.max(EventSummary.version)).where(EventSummary.event_id == event_id)
        ).scalar_one_or_none()
        version = (version_row or 0) + 1

        summary_status = EventStatus(status)
        row = EventSummary(
            id=uuid4(),
            event_id=event_id,
            version=version,
            headline=headline,
            summary=summary,
            status=summary_status,
            latest_development=latest_development,
            uncertainties=uncertainties,
            model_id=model_id,
            source_signal_ids=source_signal_ids,
            counts=counts,
        )
        self._session.add(row)

        article_count = self._session.execute(
            select(func.count(EventSignal.signal_id)).where(EventSignal.event_id == event_id)
        ).scalar_one()
        self._session.execute(
            update(Event)
            .where(Event.id == event_id)
            .values(
                headline=headline,
                summary=summary,
                status=summary_status,
                article_count=article_count,
                last_summarized_at=moment,
            )
        )
        return version

    @staticmethod
    def _observation_counts(observation: EventObservation | None) -> dict[str, object] | None:
        if observation is None:
            return None
        return {
            "data_as_of": observation.observation_date.isoformat()
            if observation.observation_date is not None
            else None,
            "confirmed_cases": observation.confirmed_cases,
            "total_cases": observation.total_cases,
            "deaths": observation.deaths,
            "new_cases": observation.new_cases,
            "new_deaths": observation.new_deaths,
        }

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
