from episignal_backend.schema_check import EXPECTED_TABLES, missing_tables


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
