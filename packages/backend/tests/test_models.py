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
    "gdelt_query_rules",
    "filter_rules",
    "rejected_sightings",
}


def test_metadata_contains_phase_one_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_observations_preserve_event_and_signal_provenance() -> None:
    table = Base.metadata.tables["event_observations"]
    targets = {foreign_key.target_fullname for foreign_key in table.foreign_keys}
    assert "events.id" in targets
    assert "signals.id" in targets


def test_signal_versions_are_unique_by_url_and_content_hash() -> None:
    table = Base.metadata.tables["signals"]
    assert table.c.url.nullable is False
    assert table.c.url.unique is not True
    assert table.c.content_hash.nullable is False
    constraint = next(
        item
        for item in table.constraints
        if getattr(item, "name", None) == "uq_signals_url_content_hash"
    )
    assert [column.name for column in constraint.columns] == ["url", "content_hash"]


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
    assert len(enum_columns) == 11

    for column in enum_columns:
        enum_class = column.type.enum_class
        assert enum_class is not None
        assert column.type.enums == [member.value for member in enum_class]


def test_discovery_method_stores_lowercase_values() -> None:
    from episignal_backend.db.types import DiscoveryMethod

    assert DiscoveryMethod.DIRECT.value == "direct"
    assert DiscoveryMethod.GDELT.value == "gdelt"
    assert [member.value for member in DiscoveryMethod] == ["direct", "gdelt"]


def test_gdelt_query_rule_table_shape() -> None:
    from episignal_backend.models import GdeltQueryRule

    table = GdeltQueryRule.__table__
    assert table.name == "gdelt_query_rules"
    assert not table.c.rule_group.nullable
    assert not table.c.query.nullable
    assert not table.c.label.nullable
    assert not table.c.language.nullable
    assert not table.c.active.nullable
    constraint_columns = {
        tuple(sorted(column.name for column in constraint.columns))
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("language", "query") in constraint_columns


def test_signal_records_discovery_provenance() -> None:
    from episignal_backend.models import Signal

    columns = Signal.__table__.c
    assert not columns.discovered_via.nullable
    assert not columns.first_seen_at.nullable
    assert columns.gdelt_seen_at.nullable
    assert columns.published_at_offset_minutes.nullable
    assert not columns.retrieval_attempts.nullable
    assert columns.query_rule_id.nullable


def test_source_records_its_domain() -> None:
    from episignal_backend.models import Source

    assert Source.__table__.c.domain.nullable
    assert Source.__table__.c.domain.unique


def test_filter_rule_groups_are_stored_as_their_values() -> None:
    from episignal_backend.db.types import FilterRuleGroup

    assert FilterRuleGroup.TITLE_EXCLUSION.value == "title_exclusion"
    assert FilterRuleGroup.DOMAIN_BLOCKLIST.value == "domain_blocklist"


def test_duplicate_is_a_processing_status() -> None:
    from episignal_backend.db.types import ProcessingStatus

    assert ProcessingStatus.DUPLICATE.value == "duplicate"


def test_filter_rules_are_unique_per_group_and_pattern() -> None:
    from episignal_backend.models import SignalFilterRule

    constraints = {constraint.name for constraint in SignalFilterRule.__table__.constraints}
    assert "uq_filter_rules_rule_group" in constraints
    assert SignalFilterRule.__tablename__ == "filter_rules"


def test_rejected_sighting_is_unique_per_canonical_url() -> None:
    from episignal_backend.models import RejectedSighting

    constraints = {constraint.name for constraint in RejectedSighting.__table__.constraints}
    assert "uq_rejected_sightings_canonical_url" in constraints


def test_rejected_sighting_keeps_its_rule_when_the_rule_is_deleted() -> None:
    from episignal_backend.models import RejectedSighting

    foreign_key = next(iter(RejectedSighting.__table__.c.filter_rule_id.foreign_keys))
    assert foreign_key.ondelete == "SET NULL"


def test_signal_points_at_its_primary_when_duplicate() -> None:
    from episignal_backend.models import Signal

    column = Signal.__table__.c.duplicate_of_signal_id
    assert column.nullable is True
    foreign_key = next(iter(column.foreign_keys))
    assert foreign_key.column.table.name == "signals"
