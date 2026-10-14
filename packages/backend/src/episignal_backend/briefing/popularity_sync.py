"""Aggregate Briefing analytics without retaining visitor identifiers."""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from episignal_backend.briefing.ranking import (
    POPULARITY_WINDOW_HOURS,
    PopularityMetricForRanking,
    calculate_baseline_ctr,
    calculate_engagement_scores,
    smooth_ctr,
)
from episignal_backend.briefing.umami import UmamiClient, UmamiEventRecord
from episignal_backend.models import Event, EventPopularityMetric

PUBLIC_EVENT_ID = re.compile(r"^EVT-[0-9A-F]{8}$")


@dataclass(frozen=True)
class PopularityAggregate:
    public_id: str
    impressions_unique: int
    briefing_opens_unique: int
    baseline_ctr: float
    smoothed_ctr: float
    engagement_score: float


@dataclass(frozen=True)
class PopularityAggregationResult:
    metrics: Mapping[str, PopularityAggregate]
    baseline_ctr: float
    impressions_total: int
    opens_total: int
    skipped_invalid_ids: int


def _event_id(record: UmamiEventRecord, known_public_ids: set[str]) -> str | None:
    value = record.properties.get("event_id")
    if not isinstance(value, str) or not PUBLIC_EVENT_ID.fullmatch(value):
        return None
    return value if value in known_public_ids else None


def aggregate_popularity(
    impression_records: Iterable[UmamiEventRecord],
    open_records: Iterable[UmamiEventRecord],
    *,
    known_public_ids: set[str],
) -> PopularityAggregationResult:
    impression_sessions: dict[str, set[str]] = {public_id: set() for public_id in known_public_ids}
    open_sessions: dict[str, set[str]] = {public_id: set() for public_id in known_public_ids}
    skipped_invalid_ids = 0

    for record in impression_records:
        if (
            record.event_name != "event_impression"
            or record.properties.get("surface") != "briefing"
        ):
            continue
        public_id = _event_id(record, known_public_ids)
        if public_id is None:
            skipped_invalid_ids += 1
            continue
        impression_sessions[public_id].add(record.session_id)

    for record in open_records:
        if record.event_name != "briefing_event_open":
            continue
        public_id = _event_id(record, known_public_ids)
        if public_id is None:
            skipped_invalid_ids += 1
            continue
        open_sessions[public_id].add(record.session_id)

    impressions_total = sum(len(sessions) for sessions in impression_sessions.values())
    opens_total = sum(len(sessions) for sessions in open_sessions.values())
    baseline_ctr = calculate_baseline_ctr(opens_total, impressions_total)
    ranking_metrics = tuple(
        PopularityMetricForRanking(
            public_id=public_id,
            impressions_unique=len(impression_sessions[public_id]),
            briefing_opens_unique=len(open_sessions[public_id]),
            baseline_ctr=baseline_ctr,
            smoothed_ctr=smooth_ctr(
                len(open_sessions[public_id]),
                len(impression_sessions[public_id]),
                baseline_ctr,
            ),
            engagement_score=None,
            calculated_at=datetime.now(UTC),
        )
        for public_id in sorted(known_public_ids)
    )
    engagement_scores = calculate_engagement_scores(ranking_metrics)
    metrics = {
        metric.public_id: PopularityAggregate(
            public_id=metric.public_id,
            impressions_unique=metric.impressions_unique,
            briefing_opens_unique=metric.briefing_opens_unique,
            baseline_ctr=baseline_ctr,
            smoothed_ctr=metric.smoothed_ctr or 0.0,
            engagement_score=engagement_scores[metric.public_id],
        )
        for metric in ranking_metrics
    }
    return PopularityAggregationResult(
        metrics=metrics,
        baseline_ctr=baseline_ctr,
        impressions_total=impressions_total,
        opens_total=opens_total,
        skipped_invalid_ids=skipped_invalid_ids,
    )


def persist_popularity_metrics(
    session: Session,
    *,
    event_ids: Mapping[str, UUID],
    metrics: Iterable[PopularityAggregate],
    window_start: datetime,
    window_end: datetime,
    calculated_at: datetime,
) -> None:
    values = [
        {
            "event_id": event_ids[metric.public_id],
            "window_start": window_start,
            "window_end": window_end,
            "impressions_unique": metric.impressions_unique,
            "briefing_opens_unique": metric.briefing_opens_unique,
            "baseline_ctr": metric.baseline_ctr,
            "smoothed_ctr": metric.smoothed_ctr,
            "engagement_score": metric.engagement_score,
            "calculated_at": calculated_at,
        }
        for metric in metrics
        if metric.public_id in event_ids
    ]
    if not values:
        return
    statement = insert(EventPopularityMetric).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=["event_id", "window_start", "window_end"],
        set_={
            "impressions_unique": statement.excluded.impressions_unique,
            "briefing_opens_unique": statement.excluded.briefing_opens_unique,
            "baseline_ctr": statement.excluded.baseline_ctr,
            "smoothed_ctr": statement.excluded.smoothed_ctr,
            "engagement_score": statement.excluded.engagement_score,
            "calculated_at": statement.excluded.calculated_at,
        },
    )
    session.execute(statement)


def sync_event_popularity(
    session: Session,
    client: UmamiClient,
    *,
    now: datetime | None = None,
) -> PopularityAggregationResult:
    effective_now = (now or datetime.now(UTC)).astimezone(UTC)
    window_start = effective_now - timedelta(hours=POPULARITY_WINDOW_HOURS)
    event_rows = session.execute(select(Event.id, Event.public_id)).all()
    event_ids = {
        public_id: event_id
        for event_id, public_id in event_rows
        if isinstance(public_id, str) and PUBLIC_EVENT_ID.fullmatch(public_id)
    }
    impressions = client.fetch_event_records("event_impression", window_start, effective_now)
    opens = client.fetch_event_records("briefing_event_open", window_start, effective_now)
    result = aggregate_popularity(impressions, opens, known_public_ids=set(event_ids))
    persist_popularity_metrics(
        session,
        event_ids=event_ids,
        metrics=result.metrics.values(),
        window_start=window_start,
        window_end=effective_now,
        calculated_at=effective_now,
    )
    return result
