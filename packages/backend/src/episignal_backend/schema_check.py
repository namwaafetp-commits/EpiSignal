"""Read-only live schema and seed identity report.

Prints JSON on stdout so `scripts/verify-live-database.ps1` can compare two runs
without embedding SQL in PowerShell. Nothing here creates, alters or deletes
anything, and no connection detail is included in the output.
"""

import json
import sys
from collections.abc import Iterable

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from episignal_backend.db.session import get_engine, session_scope
from episignal_backend.health import ComponentState, check_database
from episignal_backend.models import Disease, Signal, Source

EXPECTED_TABLES = (
    "sources",
    "signals",
    "diseases",
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
)

EXPECTED_EVENT_COLUMNS = (
    "id",
    "public_id",
    "slug",
    "title",
    "disease_id",
    "pathogen_id",
    "event_type",
    "status",
    "verification_status",
    "country_code",
    "admin1",
    "admin2",
    "latitude",
    "longitude",
    "geometry",
    "first_signal_at",
    "event_start_date",
    "last_updated_at",
    "early_signal_score",
    "evidence_score",
    "ai_summary",
    "created_at",
    "updated_at",
)

EXPECTED_SIGNAL_COLUMNS = (
    "id",
    "source_id",
    "external_id",
    "url",
    "canonical_url",
    "title",
    "normalized_title",
    "raw_text",
    "summary",
    "published_at",
    "retrieved_at",
    "language",
    "content_hash",
    "relevance_score",
    "public_health_relevant",
    "triage_status",
    "triage_category",
    "triage_disease_text",
    "triage_country_code",
    "triage_admin1",
    "triage_admin2",
    "triage_location_text",
    "triage_confidence",
    "embedding",
    "signal_type",
    "ai_extraction",
    "ai_model",
    "ai_processed_at",
    "processing_status",
    "discovered_via",
    "first_seen_at",
    "gdelt_seen_at",
    "published_at_offset_minutes",
    "retrieval_attempts",
    "query_rule_id",
    "disease_id",
    "duplicate_of_signal_id",
    "created_at",
    "updated_at",
)

SELECT_PGVECTOR_VERSION = text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")


def missing_tables(present: set[str]) -> list[str]:
    return [table for table in EXPECTED_TABLES if table not in present]


def signal_counts(rows: Iterable[tuple[str, int]]) -> dict[str, int]:
    return {name: count for name, count in rows}


def database_report(session: Session) -> dict[str, ComponentState]:
    """Return sanitized readiness states for the operator-only schema report."""
    health = check_database(session.connection())
    if health.database != "up":
        pgvector: ComponentState = "unknown"
    else:
        try:
            version = session.scalar(SELECT_PGVECTOR_VERSION)
        except Exception:
            pgvector = "down"
        else:
            pgvector = "up" if version else "down"
    return {
        "database": health.database,
        "postgis": health.postgis,
        "pgvector": pgvector,
    }


def build_report() -> dict[str, object]:
    with session_scope() as session:
        components = database_report(session)
        present = set(inspect(get_engine()).get_table_names())
        diseases = {
            slug: str(identifier)
            for slug, identifier in session.execute(select(Disease.slug, Disease.id))
        }
        sources = {
            name: str(identifier)
            for name, identifier in session.execute(select(Source.name, Source.id))
        }
        active_sources = [
            name for name, active in session.execute(select(Source.name, Source.active)) if active
        ]
        signals = signal_counts(
            session.execute(
                select(Source.name, func.count(Signal.id))
                .select_from(Source)
                .outerjoin(Signal, Signal.source_id == Source.id)
                .group_by(Source.name)
            )
            .tuples()
            .all()
        )

    return {
        **components,
        "missing_tables": missing_tables(present),
        "diseases": diseases,
        "sources": sources,
        "active_sources": active_sources,
        "signals": signals,
    }


def main() -> int:
    try:
        report = build_report()
    except Exception:
        print("schema check failed: could not read the configured database", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    return (
        0
        if report["postgis"] == "up" and report["pgvector"] == "up" and not report["missing_tables"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
