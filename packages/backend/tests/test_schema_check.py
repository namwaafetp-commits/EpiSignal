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
