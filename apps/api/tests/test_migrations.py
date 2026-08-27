import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migrations_have_one_linear_head() -> None:
    root = Path(__file__).parents[3]
    config = Config(root / "database" / "alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20260827_0003"]



def render_offline(*arguments: str) -> str:
    root = Path(__file__).parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "database/alembic.ini",
            *arguments,
            "--sql",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.lower()


def test_offline_upgrade_declares_every_core_invariant() -> None:
    sql = render_offline("upgrade", "head")
    for table in (
        "sources",
        "signals",
        "diseases",
        "pathogens",
        "events",
        "event_signals",
        "event_observations",
        "event_locations",
    ):
        assert f"create table {table}" in sql
    for fragment in (
        "gen_random_uuid()",
        "uq_sources_name",
        "uq_sources_base_url",
        "uq_sources_feed_url",
        "uq_diseases_slug",
        "uq_pathogens_slug",
        "uq_events_public_id",
        "uq_events_slug",
        "pk_event_signals",
        "source_type_values",
        "credibility_tier_values",
        "signal_type_values",
        "processing_status_values",
        "event_type_values",
        "event_status_values",
        "verification_status_values",
        "relationship_type_values",
        "location_role_values",
        "ck_signals_relevance_score_range",
        "ck_events_attention_score_range",
        "ck_events_confidence_score_range",
        "ck_event_signals_match_score_range",
        "ck_event_observations_suspected_cases_non_negative",
        "ck_event_observations_probable_cases_non_negative",
        "ck_event_observations_confirmed_cases_non_negative",
        "ck_event_observations_total_cases_non_negative",
        "ck_event_observations_new_cases_non_negative",
        "ck_event_observations_deaths_non_negative",
        "ck_event_observations_new_deaths_non_negative",
        "ck_event_observations_recoveries_non_negative",
        "ck_event_observations_hospitalizations_non_negative",
        "ck_event_observations_affected_admin_areas_non_negative",
        "ck_event_observations_cfr_range",
        "ck_event_observations_extraction_confidence_range",
        "ck_event_locations_geocoding_confidence_range",
        "ix_events_status",
        "ix_events_verification_status",
        "ix_events_disease_id",
        "ix_events_country_code",
        "ix_events_last_updated_at",
        "ix_signals_source_id",
        "ix_signals_published_at",
        "ix_signals_processing_status",
        "ix_signals_canonical_url",
        "ix_signals_content_hash",
        "ix_event_observations_event_date",
        "ix_events_geometry",
        "ix_event_locations_geometry",
    ):
        assert fragment in sql


def test_offline_downgrade_drops_dependents_before_parents() -> None:
    sql = render_offline("downgrade", "20260826_0001:base")
    assert sql.index("drop table event_locations") < sql.index("drop table events")
    assert sql.index("drop table event_observations") < sql.index("drop table events")
    assert "drop extension postgis" not in sql


def test_second_revision_versions_signals_by_content_hash() -> None:
    sql = render_offline("upgrade", "head")
    assert "uq_signals_url_content_hash" in sql
    assert "drop constraint uq_signals_url" in sql


def test_third_revision_adds_gdelt_discovery() -> None:
    sql = render_offline("upgrade", "head")
    assert "create table gdelt_query_rules" in sql
    assert "uq_gdelt_query_rules_query" in sql
    assert "discovery_method_values" in sql
    assert "ix_signals_discovered_via" in sql
    assert "ix_signals_first_seen_at" in sql
    assert "uq_sources_domain" in sql
    for column in (
        "discovered_via",
        "first_seen_at",
        "gdelt_seen_at",
        "published_at_offset_minutes",
        "retrieval_attempts",
        "query_rule_id",
    ):
        assert f"add column {column}" in sql


def test_third_revision_backfills_first_seen_at_before_enforcing_it() -> None:
    sql = render_offline("upgrade", "head")
    # The column is added nullable, filled from retrieved_at, and only then made
    # NOT NULL. Reordering these would fail on any database holding signals.
    assert sql.index("set first_seen_at = retrieved_at") < sql.index(
        "alter column first_seen_at set not null"
    )

