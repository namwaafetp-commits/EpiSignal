"""Pure Briefing ranking and popularity calculations.

This module deliberately has no database, HTTP, or framework dependencies. The
dashboard read path and the scheduled popularity sync both use these functions
so shadow-mode ranking and activated ranking cannot drift apart.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

RECENCY_WEIGHT = 0.65
ENGAGEMENT_WEIGHT = 0.35
RECENCY_TAU_HOURS = 36.0
PRIOR_STRENGTH = 20.0
POPULARITY_WINDOW_HOURS = 48
METRICS_STALE_AFTER_MINUTES = 60
MIN_EXPOSURES_FOR_ENGAGEMENT = 5


@dataclass(frozen=True)
class BriefingEventForRanking:
    public_id: str
    published_at: datetime | str | None


@dataclass(frozen=True)
class PopularityMetricForRanking:
    public_id: str
    impressions_unique: int
    briefing_opens_unique: int
    baseline_ctr: float | None
    smoothed_ctr: float | None
    engagement_score: float | None
    calculated_at: datetime


@dataclass(frozen=True)
class RankedBriefingEvent:
    event: BriefingEventForRanking
    recency_score: float
    engagement_score: float
    ranking_score: float


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _as_utc(value: datetime | str | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def recency_score(
    published_at: datetime | str | None,
    *,
    now: datetime,
) -> float:
    """Return ``exp(-age_hours / 36)`` safely clamped to the unit interval."""

    published = _as_utc(published_at)
    current = _as_utc(now)
    if published is None or current is None:
        return 0.0
    age_hours = max(0.0, (current - published).total_seconds() / 3600)
    return _clamp(math.exp(-age_hours / RECENCY_TAU_HOURS))


def calculate_baseline_ctr(opens: object, impressions: object) -> float:
    opening_count = _finite_number(opens)
    impression_count = _finite_number(impressions)
    if (
        opening_count is None
        or impression_count is None
        or impression_count <= 0
        or opening_count < 0
    ):
        return 0.0
    return _clamp(opening_count / impression_count)


def smooth_ctr(opens: object, impressions: object, baseline_ctr: object) -> float:
    opening_count = _finite_number(opens)
    impression_count = _finite_number(impressions)
    baseline = _finite_number(baseline_ctr)
    if (
        opening_count is None
        or impression_count is None
        or baseline is None
        or opening_count < 0
        or impression_count < 0
    ):
        return 0.0
    denominator = impression_count + PRIOR_STRENGTH
    if denominator <= 0:
        return 0.0
    return _clamp((opening_count + PRIOR_STRENGTH * _clamp(baseline)) / denominator)


def percentile_scores(values: Sequence[float]) -> tuple[float, ...]:
    """Convert values to deterministic mid-rank percentiles in input order."""

    if not values:
        return ()
    if len(values) == 1:
        return (0.5,)
    indexed = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    scores = [0.5] * len(values)
    index = 0
    while index < len(indexed):
        end = index + 1
        while end < len(indexed) and indexed[end][1] == indexed[index][1]:
            end += 1
        average_rank = (index + end - 1) / 2
        percentile = _clamp(average_rank / (len(values) - 1))
        for original_index, _ in indexed[index:end]:
            scores[original_index] = percentile
        index = end
    return tuple(scores)


def calculate_engagement_scores(
    metrics: Sequence[PopularityMetricForRanking],
) -> dict[str, float]:
    """Calculate neutral-or-percentile engagement scores from raw aggregates."""

    total_impressions = sum(
        value
        for metric in metrics
        if (value := _finite_number(metric.impressions_unique)) is not None and value >= 0
    )
    total_opens = sum(
        value
        for metric in metrics
        if (value := _finite_number(metric.briefing_opens_unique)) is not None and value >= 0
    )
    baseline = calculate_baseline_ctr(total_opens, total_impressions)
    eligible: list[tuple[str, float]] = []
    scores = {metric.public_id: 0.50 for metric in metrics}
    for metric in metrics:
        impressions = _finite_number(metric.impressions_unique)
        opens = _finite_number(metric.briefing_opens_unique)
        if (
            impressions is None
            or opens is None
            or impressions < MIN_EXPOSURES_FOR_ENGAGEMENT
            or opens < 0
        ):
            continue
        eligible.append((metric.public_id, smooth_ctr(opens, impressions, baseline)))
    percentiles = percentile_scores([value for _, value in eligible])
    for (public_id, _), percentile in zip(eligible, percentiles, strict=True):
        scores[public_id] = percentile
    return scores


def _metric_is_trusted(metric: PopularityMetricForRanking, *, now: datetime) -> bool:
    calculated_at = _as_utc(metric.calculated_at)
    engagement = _finite_number(metric.engagement_score)
    if calculated_at is None or engagement is None or not 0 <= engagement <= 1:
        return False
    age_minutes = (now.astimezone(UTC) - calculated_at).total_seconds() / 60
    return 0 <= age_minutes <= METRICS_STALE_AFTER_MINUTES


def rank_briefing_events(
    events: Sequence[BriefingEventForRanking],
    metrics: Mapping[str, PopularityMetricForRanking],
    *,
    now: datetime,
    enabled: bool,
) -> tuple[RankedBriefingEvent, ...]:
    """Score and order events once, with recency-only failure behavior."""

    if not enabled:
        return tuple(
            RankedBriefingEvent(
                event=event,
                recency_score=recency_score(event.published_at, now=now),
                engagement_score=0.50,
                ranking_score=0.0,
            )
            for event in events
        )

    trusted = bool(metrics) and all(
        _metric_is_trusted(metric, now=now) for metric in metrics.values()
    )
    scored: list[RankedBriefingEvent] = []
    for event in events:
        recent = recency_score(event.published_at, now=now)
        metric_engagement = (
            _finite_number(metrics[event.public_id].engagement_score)
            if trusted and event.public_id in metrics
            else None
        )
        engagement = metric_engagement if metric_engagement is not None else 0.50
        final = (
            _clamp(RECENCY_WEIGHT * recent + ENGAGEMENT_WEIGHT * engagement) if trusted else recent
        )
        scored.append(
            RankedBriefingEvent(
                event=event,
                recency_score=recent,
                engagement_score=engagement,
                ranking_score=final,
            )
        )

    def timestamp_key(item: RankedBriefingEvent) -> datetime:
        return _as_utc(item.event.published_at) or datetime.min.replace(tzinfo=UTC)

    return tuple(
        sorted(
            scored,
            key=lambda item: (
                -item.ranking_score,
                -timestamp_key(item).timestamp(),
                item.event.public_id,
            ),
        )
    )
