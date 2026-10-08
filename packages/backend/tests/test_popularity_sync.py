from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from episignal_backend.briefing.popularity_sync import (
    aggregate_popularity,
    persist_popularity_metrics,
)
from episignal_backend.briefing.umami import UmamiEventRecord

NOW = datetime(2026, 9, 17, 12, tzinfo=UTC)


def record(
    event_name: str,
    session_id: str,
    event_id: str,
    *,
    surface: str = "briefing",
) -> UmamiEventRecord:
    return UmamiEventRecord(
        event_name=event_name,
        session_id=session_id,
        properties={"event_id": event_id, "surface": surface},
    )


def test_aggregation_deduplicates_sessions_filters_surface_and_skips_invalid_ids() -> None:
    impressions = [
        record("event_impression", "session-a", "EVT-00000001"),
        record("event_impression", "session-a", "EVT-00000001"),
        record("event_impression", "session-b", "EVT-00000001"),
        record("event_impression", "session-c", "EVT-00000002", surface="map"),
        record("event_impression", "session-d", "EVT-99999999"),
        record("event_impression", "session-e", "internal-event"),
    ]
    opens = [
        record("briefing_event_open", "session-a", "EVT-00000001"),
        record("briefing_event_open", "session-a", "EVT-00000001"),
        record("briefing_event_open", "session-b", "EVT-00000002"),
    ]

    result = aggregate_popularity(
        impressions,
        opens,
        known_public_ids={"EVT-00000001", "EVT-00000002"},
    )

    assert result.skipped_invalid_ids == 2
    assert result.impressions_total == 2
    assert result.opens_total == 2
    assert result.metrics["EVT-00000001"].impressions_unique == 2
    assert result.metrics["EVT-00000001"].briefing_opens_unique == 1
    assert result.metrics["EVT-00000002"].impressions_unique == 0
    assert result.metrics["EVT-00000002"].engagement_score == 0.50
    assert all("session" not in vars(metric) for metric in result.metrics.values())


def test_aggregation_calculates_bayesian_scores_and_neutral_unexposed_events() -> None:
    impressions = [
        record("event_impression", f"a-{index}", "EVT-00000001") for index in range(5)
    ] + [record("event_impression", f"b-{index}", "EVT-00000002") for index in range(5)]
    opens = [record("briefing_event_open", f"a-{index}", "EVT-00000001") for index in range(2)]

    result = aggregate_popularity(
        impressions,
        opens,
        known_public_ids={"EVT-00000001", "EVT-00000002", "EVT-00000003"},
    )

    assert result.baseline_ctr == 0.2
    assert result.metrics["EVT-00000001"].smoothed_ctr == (2 + 20 * 0.2) / 25
    assert result.metrics["EVT-00000003"].engagement_score == 0.50
    assert all(0.0 <= metric.engagement_score <= 1.0 for metric in result.metrics.values())


def test_persist_upserts_aggregate_rows_without_session_identifiers() -> None:
    metric = SimpleNamespace(
        public_id="EVT-00000001",
        impressions_unique=5,
        briefing_opens_unique=2,
        baseline_ctr=0.4,
        smoothed_ctr=0.4,
        engagement_score=0.5,
    )
    session = SimpleNamespace(execute=lambda statement: setattr(session, "statement", statement))
    persist_popularity_metrics(
        session,
        event_ids={"EVT-00000001": __import__("uuid").uuid4()},
        metrics=(metric,),
        window_start=NOW - timedelta(hours=48),
        window_end=NOW,
        calculated_at=NOW,
    )

    sql = str(session.statement.compile(compile_kwargs={"literal_binds": True}))
    assert "event_popularity_metrics" in sql
    assert "session-a" not in sql
    assert "visitor" not in sql.lower()
