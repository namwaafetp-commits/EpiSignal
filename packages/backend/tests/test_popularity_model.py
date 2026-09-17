from pathlib import Path

from episignal_backend.models import EventPopularityMetric


def test_popularity_metric_is_an_aggregate_only_event_window_model() -> None:
    table = EventPopularityMetric.__table__

    assert table.name == "event_popularity_metrics"
    assert {column.name for column in table.columns} == {
        "id",
        "event_id",
        "window_start",
        "window_end",
        "impressions_unique",
        "briefing_opens_unique",
        "baseline_ctr",
        "smoothed_ctr",
        "engagement_score",
        "calculated_at",
    }
    assert "event_id" in {foreign_key.parent.name for foreign_key in table.foreign_keys}
    assert any(
        set(constraint.columns.keys()) == {"event_id", "window_start", "window_end"}
        for constraint in table.constraints
        if hasattr(constraint, "columns")
    )
    assert {index.name for index in table.indexes} >= {
        "ix_event_popularity_metrics_event",
        "ix_event_popularity_metrics_event_window_end",
    }


def test_popularity_migration_follows_actual_current_head() -> None:
    migration = Path(__file__).parents[3] / (
        "database/migrations/versions/20260917_0026_event_popularity_metrics.py"
    )
    source = migration.read_text(encoding="utf-8")

    assert 'revision: str = "20260917_0026"' in source
    assert 'down_revision: str | None = "20260912_0025"' in source
    assert source.count("op.create_table") == 1
    assert "event_popularity_metrics" in source
