"""Keep application tables behind the server-owned API boundary."""

from collections.abc import Sequence

from alembic import op

revision: str = "20261104_0028"
down_revision: str | None = "20261103_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "ai_models",
    "ai_requests",
    "alembic_version",
    "diseases",
    "event_locations",
    "event_observations",
    "event_popularity_metrics",
    "event_signals",
    "event_summaries",
    "events",
    "filter_rules",
    "gazetteer_places",
    "gdelt_discovery_state",
    "gdelt_query_rules",
    "geocode_cache",
    "pathogens",
    "pipeline_health_runs",
    "pipeline_runs",
    "rejected_sightings",
    "signal_locations",
    "signal_review_candidates",
    "signal_review_cases",
    "signals",
    "sources",
    "story_group_members",
    "story_groups",
)


def upgrade() -> None:
    statements = []
    for table in TABLES:
        statements.append(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY;')
        statements.append(f'REVOKE ALL ON TABLE public."{table}" FROM PUBLIC, anon, authenticated;')
    for kind in ("TABLES", "SEQUENCES"):
        statements.append(
            "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public "
            f"REVOKE ALL ON {kind} FROM PUBLIC, anon, authenticated;"
        )
    # One round trip keeps exclusive table locks short on remote connections.
    op.execute("DO $security$ BEGIN\n" + "\n".join(statements) + "\nEND $security$;")


def downgrade() -> None:
    raise RuntimeError(
        "Keep the security boundary during application rollback; "
        "permission restoration requires a reviewed ACL snapshot."
    )
