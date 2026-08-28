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
    "ai_models",
    "ai_requests",
    "gazetteer_places",
    "signal_locations",
    "pipeline_runs",
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
    assert len(enum_columns) == 19

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


def test_ai_purposes_are_stored_as_their_values() -> None:
    from episignal_backend.db.types import AiPurpose

    assert AiPurpose.CLASSIFICATION.value == "classification"
    assert AiPurpose.EXTRACTION.value == "extraction"


def test_ai_outcomes_separate_a_refusal_from_a_bad_answer() -> None:
    from episignal_backend.db.types import AiOutcome

    assert AiOutcome.ACCEPTED.value == "accepted"
    assert AiOutcome.REJECTED.value == "rejected"
    assert AiOutcome.UNAVAILABLE.value == "unavailable"


def test_the_model_roster_orders_the_ladder_by_tier() -> None:
    from episignal_backend.models import AiModel

    assert AiModel.__tablename__ == "ai_models"
    assert {"tier", "model_id", "prompt_price_per_million"} <= set(AiModel.__table__.columns.keys())
    assert AiModel.__table__.columns["model_id"].unique is True


def test_a_cost_row_keeps_the_price_that_was_charged() -> None:
    from episignal_backend.models import AiRequest

    columns = set(AiRequest.__table__.columns.keys())

    assert {
        "model_id",
        "tier",
        "purpose",
        "signal_id",
        "batch_size",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "http_status",
        "outcome",
        "rejection_reason",
        "prompt_price_per_million",
        "completion_price_per_million",
        "cost_usd",
        "requested_at",
    } <= columns


def test_retiring_a_model_does_not_delete_its_spend() -> None:
    from episignal_backend.models import AiRequest

    foreign_key = next(
        key for key in AiRequest.__table__.foreign_keys if key.column.table.name == "ai_models"
    )

    assert foreign_key.ondelete == "SET NULL"


def test_a_signal_links_to_the_disease_it_resolved_to() -> None:
    from episignal_backend.models import Signal

    assert "disease_id" in Signal.__table__.columns
    assert Signal.__table__.columns["disease_id"].nullable is True


def test_the_gazetteer_is_keyed_on_its_geonames_id() -> None:
    from episignal_backend.models import GazetteerPlace

    assert GazetteerPlace.__tablename__ == "gazetteer_places"
    primary_key = [column.name for column in GazetteerPlace.__table__.primary_key]
    assert primary_key == ["geonames_id"]


def test_the_gazetteer_indexes_both_name_forms() -> None:
    from episignal_backend.models import GazetteerPlace

    indexed = {
        tuple(column.name for column in index.columns) for index in GazetteerPlace.__table__.indexes
    }
    assert ("normalized_name",) in indexed
    assert ("ascii_name",) in indexed
    assert ("country_code", "admin1_code", "normalized_name") in indexed


def test_a_signal_location_may_hold_no_coordinate() -> None:
    from episignal_backend.models import SignalLocation

    columns = SignalLocation.__table__.columns
    assert columns["latitude"].nullable
    assert columns["longitude"].nullable
    assert columns["geocoding_confidence"].nullable
    assert not columns["precision"].nullable


def test_a_signal_location_keeps_the_extraction_strings_and_the_resolution() -> None:
    from episignal_backend.models import SignalLocation

    names = set(SignalLocation.__table__.columns.keys())
    assert {"country_name", "admin1_name", "place_name"} <= names
    assert {"resolved_name", "geonames_id", "country_code", "admin1", "admin2"} <= names
    assert {"geocoding_source", "geocoding_confidence", "precision"} <= names


def test_signal_locations_are_indexed_for_spatial_matching() -> None:
    from episignal_backend.models import SignalLocation

    indexed = {
        tuple(column.name for column in index.columns) for index in SignalLocation.__table__.indexes
    }
    assert ("geometry",) in indexed
    assert ("signal_id",) in indexed


def test_event_exposes_renamed_score_columns_and_constraints() -> None:
    from episignal_backend.models import Event

    columns = set(Event.__table__.columns.keys())
    assert "early_signal_score" in columns
    assert "evidence_score" in columns
    assert "attention_score" not in columns
    assert "confidence_score" not in columns

    constraint_names = {c.name for c in Event.__table__.constraints if c.name is not None}
    assert any("early_signal_score_range" in name for name in constraint_names)
    assert any("evidence_score_range" in name for name in constraint_names)
    assert not any("attention_score_range" in name for name in constraint_names)
    assert not any("confidence_score_range" in name for name in constraint_names)

    constraints = {c.name: c for c in Event.__table__.constraints if c.name is not None}
    early_constraint = next(
        c for name, c in constraints.items() if "early_signal_score_range" in name
    )
    evidence_constraint = next(
        c for name, c in constraints.items() if "evidence_score_range" in name
    )
    early_sql = str(early_constraint.sqltext)
    evidence_sql = str(evidence_constraint.sqltext)

    assert "early_signal_score >= 0" in early_sql and "early_signal_score <= 1" in early_sql
    assert "evidence_score >= 0" in evidence_sql and "evidence_score <= 1" in evidence_sql


def test_a_pipeline_run_records_the_window_it_asked_for() -> None:
    table = Base.metadata.tables["pipeline_runs"]

    assert {"window_start", "window_end"} <= set(table.columns.keys())
    assert table.columns["window_start"].nullable is True


def test_a_pipeline_run_starts_before_it_finishes() -> None:
    table = Base.metadata.tables["pipeline_runs"]

    assert table.columns["started_at"].nullable is False
    # Null until the run closes out, which is how a killed run is recognised.
    assert table.columns["finished_at"].nullable is True


def test_stage_counts_and_backlog_default_to_empty_rather_than_null() -> None:
    table = Base.metadata.tables["pipeline_runs"]

    for name in ("stage_counts", "backlog", "failed_stages"):
        assert table.columns[name].nullable is False

