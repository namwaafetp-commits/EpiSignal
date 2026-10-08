from episignal_backend.schema_check import (
    EXPECTED_SIGNAL_COLUMNS,
    EXPECTED_TABLES,
    database_report,
    missing_tables,
)


class HealthyConnection:
    def scalar(self, statement: object) -> object:
        return "3.5 USE_GEOS=1" if "postgis_full_version" in str(statement) else 1


class PgvectorSession:
    def connection(self) -> HealthyConnection:
        return HealthyConnection()

    def scalar(self, statement: object) -> object:
        assert "pg_extension" in str(statement)
        return "0.8.1"


def test_the_health_check_reports_pgvector() -> None:
    report = database_report(PgvectorSession())  # type: ignore[arg-type]

    assert report["pgvector"] == "up"


def test_the_expected_signal_columns_include_the_embedding() -> None:
    assert "embedding" in EXPECTED_SIGNAL_COLUMNS


def test_no_missing_tables_when_every_core_table_is_present() -> None:
    assert missing_tables({*EXPECTED_TABLES, "alembic_version"}) == []


def test_missing_tables_are_reported_in_declaration_order() -> None:
    assert missing_tables({"sources", "diseases"}) == [
        "signals",
        "pathogens",
        "events",
        "event_signals",
        "event_observations",
        "event_locations",
        "gazetteer_places",
        "signal_locations",
        "pipeline_runs",
        "pipeline_health_runs",
        "signal_review_cases",
        "signal_review_candidates",
        "geocode_cache",
    ]


def test_signal_counts_report_zero_for_a_source_with_no_signals() -> None:
    from episignal_backend.schema_check import signal_counts

    assert signal_counts([("WHO Disease Outbreak News", 0)]) == {"WHO Disease Outbreak News": 0}


def test_signal_counts_preserve_each_source_total() -> None:
    from episignal_backend.schema_check import signal_counts

    assert signal_counts([("WHO Disease Outbreak News", 42), ("ECDC", 0)]) == {
        "WHO Disease Outbreak News": 42,
        "ECDC": 0,
    }


def test_the_expected_tables_include_the_geocoding_tables() -> None:
    from episignal_backend.schema_check import EXPECTED_TABLES

    assert "gazetteer_places" in EXPECTED_TABLES
    assert "signal_locations" in EXPECTED_TABLES


def test_the_expected_event_columns_include_renamed_scores_and_neither_old_name() -> None:
    from episignal_backend.schema_check import EXPECTED_EVENT_COLUMNS

    assert "early_signal_score" in EXPECTED_EVENT_COLUMNS
    assert "evidence_score" in EXPECTED_EVENT_COLUMNS
    assert "attention_score" not in EXPECTED_EVENT_COLUMNS
    assert "confidence_score" not in EXPECTED_EVENT_COLUMNS


def test_the_schema_check_expects_the_pipeline_runs_table() -> None:
    from episignal_backend.schema_check import EXPECTED_TABLES

    assert "pipeline_runs" in EXPECTED_TABLES


def test_the_schema_check_expects_the_pipeline_health_table() -> None:
    from episignal_backend.schema_check import EXPECTED_TABLES

    assert "pipeline_health_runs" in EXPECTED_TABLES


def test_a_database_without_pipeline_runs_is_reported_as_missing_it() -> None:
    from episignal_backend.schema_check import EXPECTED_TABLES, missing_tables

    present = {table for table in EXPECTED_TABLES if table != "pipeline_runs"}

    assert missing_tables(present) == ["pipeline_runs"]
