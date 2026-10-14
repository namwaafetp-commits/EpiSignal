from datetime import UTC, datetime, timedelta

import pytest
from episignal_backend.briefing.ranking import (
    ENGAGEMENT_WEIGHT,
    PRIOR_STRENGTH,
    RECENCY_TAU_HOURS,
    RECENCY_WEIGHT,
    BriefingEventForRanking,
    PopularityMetricForRanking,
    calculate_baseline_ctr,
    calculate_engagement_scores,
    percentile_scores,
    rank_briefing_events,
    recency_score,
    smooth_ctr,
)

NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)


def event(public_id: str, age_hours: float | None) -> BriefingEventForRanking:
    return BriefingEventForRanking(
        public_id=public_id,
        published_at=(NOW - timedelta(hours=age_hours) if age_hours is not None else None),
    )


def metric(
    public_id: str,
    *,
    impressions: int,
    opens: int,
    engagement: float | None = None,
    calculated_at: datetime = NOW,
) -> PopularityMetricForRanking:
    return PopularityMetricForRanking(
        public_id=public_id,
        impressions_unique=impressions,
        briefing_opens_unique=opens,
        baseline_ctr=None,
        smoothed_ctr=None,
        engagement_score=engagement,
        calculated_at=calculated_at,
    )


def test_ranking_constants_match_the_briefing_spec() -> None:
    assert RECENCY_WEIGHT == 0.65
    assert ENGAGEMENT_WEIGHT == 0.35
    assert RECENCY_TAU_HOURS == 36
    assert PRIOR_STRENGTH == 20


@pytest.mark.parametrize(
    ("age_hours", "expected"),
    [(0, 1.0), (6, 0.8465), (12, 0.7165), (24, 0.5134), (48, 0.2636), (72, 0.1353)],
)
def test_recency_score_uses_the_utc_exponential_decay(age_hours: float, expected: float) -> None:
    assert recency_score(NOW - timedelta(hours=age_hours), now=NOW) == pytest.approx(
        expected, abs=0.001
    )


def test_recency_score_clamps_future_and_invalid_timestamps() -> None:
    assert recency_score(NOW + timedelta(hours=12), now=NOW) == 1.0
    assert recency_score(None, now=NOW) == 0.0
    assert recency_score("not-a-date", now=NOW) == 0.0


def test_baseline_ctr_handles_zero_and_invalid_counts() -> None:
    assert calculate_baseline_ctr(40, 100) == 0.4
    assert calculate_baseline_ctr(40, 0) == 0.0
    assert calculate_baseline_ctr(-1, 100) == 0.0
    assert calculate_baseline_ctr(float("nan"), 100) == 0.0


def test_smooth_ctr_uses_the_named_bayesian_prior() -> None:
    assert smooth_ctr(1, 1, 0.4) == pytest.approx((1 + PRIOR_STRENGTH * 0.4) / 21)
    assert smooth_ctr(0, 0, 0.4) == pytest.approx(0.4)
    assert smooth_ctr(1, 1, float("nan")) == 0.0


def test_percentile_scores_are_deterministic_and_use_mid_ranks_for_ties() -> None:
    assert percentile_scores([0.1, 0.2, 0.2, 0.9]) == pytest.approx((0.0, 0.5, 0.5, 1.0))
    assert percentile_scores([0.2, 0.2, 0.2]) == pytest.approx((0.5, 0.5, 0.5))
    assert percentile_scores([0.9]) == (0.5,)


def test_insufficient_exposure_gets_neutral_engagement() -> None:
    scores = calculate_engagement_scores(
        [
            metric("EVT-A", impressions=1, opens=1),
            metric("EVT-B", impressions=100, opens=40),
        ]
    )

    assert scores["EVT-A"] == 0.50
    assert 0.0 <= scores["EVT-B"] <= 1.0


def test_ranking_disabled_preserves_input_order() -> None:
    events = [event("EVT-B", 48), event("EVT-A", 0)]

    ranked = rank_briefing_events(events, {}, now=NOW, enabled=False)

    assert [item.event.public_id for item in ranked] == ["EVT-B", "EVT-A"]


def test_same_popularity_prefers_newer_event() -> None:
    events = [event("EVT-OLD", 24), event("EVT-NEW", 0)]
    metrics = {
        "EVT-OLD": metric("EVT-OLD", impressions=100, opens=40, engagement=0.5),
        "EVT-NEW": metric("EVT-NEW", impressions=100, opens=40, engagement=0.5),
    }

    ranked = rank_briefing_events(events, metrics, now=NOW, enabled=True)

    assert [item.event.public_id for item in ranked] == ["EVT-NEW", "EVT-OLD"]


def test_moderately_older_high_engagement_event_can_receive_a_boost() -> None:
    events = [event("EVT-NEW", 0), event("EVT-OLDER", 6)]
    metrics = {
        "EVT-NEW": metric("EVT-NEW", impressions=100, opens=40, engagement=0.1),
        "EVT-OLDER": metric("EVT-OLDER", impressions=100, opens=40, engagement=1.0),
    }

    ranked = rank_briefing_events(events, metrics, now=NOW, enabled=True)

    assert ranked[0].event.public_id == "EVT-OLDER"


def test_very_old_event_does_not_dominate_solely_from_engagement() -> None:
    events = [event("EVT-NEW", 0), event("EVT-OLD", 72)]
    metrics = {
        "EVT-NEW": metric("EVT-NEW", impressions=100, opens=40, engagement=0.0),
        "EVT-OLD": metric("EVT-OLD", impressions=100, opens=40, engagement=1.0),
    }

    ranked = rank_briefing_events(events, metrics, now=NOW, enabled=True)

    assert ranked[0].event.public_id == "EVT-NEW"


def test_missing_stale_or_malformed_metrics_use_recency_only() -> None:
    events = [event("EVT-OLD", 24), event("EVT-NEW", 0)]
    stale = {
        "EVT-OLD": metric(
            "EVT-OLD",
            impressions=100,
            opens=40,
            engagement=1.0,
            calculated_at=NOW - timedelta(minutes=61),
        ),
        "EVT-NEW": metric("EVT-NEW", impressions=100, opens=40, engagement=float("nan")),
    }

    ranked = rank_briefing_events(events, stale, now=NOW, enabled=True)

    assert [item.event.public_id for item in ranked] == ["EVT-NEW", "EVT-OLD"]
    assert ranked[0].ranking_score == pytest.approx(1.0)


def test_ranked_ties_use_timestamp_then_public_id_and_scores_stay_bounded() -> None:
    timestamp = event("EVT-B", 6).published_at
    assert timestamp is not None
    events = [
        BriefingEventForRanking("EVT-B", timestamp),
        BriefingEventForRanking("EVT-A", timestamp),
    ]
    metrics = {
        public_id: metric(public_id, impressions=100, opens=40, engagement=0.5)
        for public_id in ("EVT-A", "EVT-B")
    }

    ranked = rank_briefing_events(events, metrics, now=NOW, enabled=True)

    assert [item.event.public_id for item in ranked] == ["EVT-A", "EVT-B"]
    assert all(0.0 <= item.ranking_score <= 1.0 for item in ranked)
