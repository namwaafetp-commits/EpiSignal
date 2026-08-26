import episignal_backend.models  # noqa: F401
from episignal_backend.db.base import Base
from sqlalchemy import Enum

EXPECTED_TABLES = {
    "sources",
    "signals",
    "diseases",
    "pathogens",
    "events",
    "event_signals",
    "event_observations",
    "event_locations",
}


def test_metadata_contains_phase_one_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_observations_preserve_event_and_signal_provenance() -> None:
    table = Base.metadata.tables["event_observations"]
    targets = {foreign_key.target_fullname for foreign_key in table.foreign_keys}
    assert "events.id" in targets
    assert "signals.id" in targets


def test_signal_original_url_is_unique_and_required() -> None:
    url = Base.metadata.tables["signals"].c.url
    assert url.nullable is False
    assert url.unique is True


def test_database_generates_uuid_primary_keys() -> None:
    source_id = Base.metadata.tables["sources"].c.id
    assert source_id.default is None
    assert str(source_id.server_default.arg) == "gen_random_uuid()"


def test_source_name_is_a_stable_unique_seed_key() -> None:
    name = Base.metadata.tables["sources"].c.name
    assert name.nullable is False
    assert name.unique is True


def test_catalog_natural_keys_and_source_urls_are_unique() -> None:
    assert Base.metadata.tables["sources"].c.base_url.unique is True
    assert Base.metadata.tables["sources"].c.feed_url.unique is True
    assert Base.metadata.tables["diseases"].c.slug.unique is True
    assert Base.metadata.tables["pathogens"].c.slug.unique is True


def test_event_signal_relationship_has_composite_primary_key() -> None:
    table = Base.metadata.tables["event_signals"]
    assert [column.name for column in table.primary_key.columns] == ["event_id", "signal_id"]


def test_location_uses_postgis_geography() -> None:
    assert str(Base.metadata.tables["event_locations"].c.geometry.type) == "geography(POINT,4326)"


def test_enum_columns_persist_vocabulary_values_not_member_names() -> None:
    enum_columns = [
        column
        for table in Base.metadata.tables.values()
        for column in table.c
        if isinstance(column.type, Enum)
    ]
    assert len(enum_columns) == 9
    for column in enum_columns:
        enum_class = column.type.enum_class
        assert enum_class is not None
        assert column.type.enums == [member.value for member in enum_class]
