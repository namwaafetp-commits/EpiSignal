"""manual review cases

Revision ID: 20260829_0014
Revises: 20260829_0013
Create Date: 2026-08-29

Durable review cases and candidate event snapshots:
- Expand processing_status check constraint with 'dismissed'.
- Create signal_review_cases and signal_review_candidates tables, constraints, and indexes.
- Conservatively backfill one open case for every signal at needs_review.
- Verify per-signal cardinality before committing.
- Guard downgrade against erasing live review history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0014"
down_revision: str | None = "20260829_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROCESSING_STATUSES = (
    "fetched",
    "normalized",
    "classified",
    "extracted",
    "geocoded",
    "matched",
    "published",
    "duplicate",
    "failed",
    "needs_review",
    "dismissed",
)

PREVIOUS_PROCESSING_STATUSES = tuple(
    status for status in PROCESSING_STATUSES if status != "dismissed"
)

_REVIEW_REASONS = (
    "retrieval_failed",
    "extraction_rejected",
    "disease_unresolved",
    "location_unresolved",
    "event_match_ambiguous",
    "content_integrity",
    "legacy_unclassified",
)

_REVIEW_STATUSES = (
    "open",
    "resolved",
)

_REVIEW_RESOLUTIONS = (
    "retry_retrieval",
    "retry_extraction",
    "assign_disease",
    "retry_geocoding",
    "link_event",
    "create_event",
    "dismiss",
    "recovered_automatically",
)


def _values(statuses: tuple[str, ...]) -> str:
    return ", ".join(f"'{status}'" for status in statuses)


def upgrade() -> None:
    # 1. Expand processing_status constraint on signals table
    op.drop_constraint("processing_status_values", "signals", type_="check")
    op.create_check_constraint(
        "processing_status_values",
        "signals",
        f"processing_status IN ({_values(PROCESSING_STATUSES)})",
    )

    # 2. Create signal_review_cases table
    op.create_table(
        "signal_review_cases",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "signal_id",
            sa.Uuid(),
            sa.ForeignKey("signals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Enum(
                *_REVIEW_REASONS,
                name="review_reason_values",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                *_REVIEW_STATUSES,
                name="review_status_values",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolution",
            sa.Enum(
                *_REVIEW_RESOLUTIONS,
                name="review_resolution_values",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("reviewed_by", sa.String(120), nullable=True),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column(
            "selected_disease_id",
            sa.Uuid(),
            sa.ForeignKey("diseases.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "selected_event_id",
            sa.Uuid(),
            sa.ForeignKey("events.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_signal_review_cases"),
        sa.CheckConstraint(
            "(status = 'open' AND resolution IS NULL AND resolved_at IS NULL) OR "
            "(status = 'resolved' AND resolution IS NOT NULL AND resolved_at IS NOT NULL)",
            name="review_resolution_state",
        ),
        sa.CheckConstraint(
            "(resolution != 'assign_disease' AND selected_disease_id IS NULL) OR "
            "(resolution = 'assign_disease' AND selected_disease_id IS NOT NULL)",
            name="review_assign_disease_target",
        ),
        sa.CheckConstraint(
            "(resolution NOT IN ('link_event', 'create_event') AND selected_event_id IS NULL) OR "
            "(resolution IN ('link_event', 'create_event') AND selected_event_id IS NOT NULL)",
            name="review_event_target",
        ),
    )
    op.create_index(
        "uq_signal_review_cases_one_open",
        "signal_review_cases",
        ["signal_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_signal_review_cases_queue",
        "signal_review_cases",
        ["status", "opened_at", "id"],
    )
    op.create_index(
        "ix_signal_review_cases_signal_id",
        "signal_review_cases",
        ["signal_id"],
    )
    op.create_index(
        "ix_signal_review_cases_selected_disease_id",
        "signal_review_cases",
        ["selected_disease_id"],
    )
    op.create_index(
        "ix_signal_review_cases_selected_event_id",
        "signal_review_cases",
        ["selected_event_id"],
    )

    # 3. Create signal_review_candidates table
    op.create_table(
        "signal_review_candidates",
        sa.Column(
            "review_case_id",
            sa.Uuid(),
            sa.ForeignKey("signal_review_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("match_score", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("review_case_id", "event_id", name="pk_signal_review_candidates"),
        sa.CheckConstraint(
            "match_score >= 0 AND match_score <= 1",
            name="match_score_range",
        ),
    )
    op.create_index(
        "ix_signal_review_candidates_event_id",
        "signal_review_candidates",
        ["event_id"],
    )

    # 4. Conservative backfill of existing needs_review signals
    op.execute(
        sa.text(
            """
            INSERT INTO signal_review_cases (
                id,
                signal_id,
                reason,
                status,
                opened_at,
                created_at,
                updated_at
            )
            SELECT
                gen_random_uuid(),
                s.id,
                CASE
                    WHEN s.id = '852aa204-846d-4aa6-a256-82c187fdeaef'::uuid
                        THEN 'content_integrity'
                    WHEN s.raw_text IS NULL OR trim(s.raw_text) = ''
                        THEN 'retrieval_failed'
                    WHEN s.ai_extraction IS NULL AND EXISTS (
                        SELECT 1 FROM ai_requests r
                        WHERE r.signal_id = s.id AND r.outcome = 'rejected'
                    ) THEN 'extraction_rejected'
                    WHEN s.ai_extraction IS NOT NULL AND s.disease_id IS NULL
                        THEN 'disease_unresolved'
                    ELSE 'legacy_unclassified'
                END,
                'open',
                COALESCE(s.first_seen_at, s.created_at, now()),
                now(),
                now()
            FROM signals s
            WHERE s.processing_status = 'needs_review'
            ON CONFLICT (signal_id) WHERE status = 'open' DO NOTHING
            """
        )
    )

    # 5. Online-only cardinality and sanity check
    if not op.get_context().as_sql:
        conn = op.get_bind()
        unreconciled = conn.execute(
            sa.text(
                """
                SELECT s.id
                FROM signals AS s
                LEFT JOIN signal_review_cases AS c
                  ON c.signal_id = s.id AND c.status = 'open'
                WHERE s.processing_status = 'needs_review'
                GROUP BY s.id
                HAVING count(c.id) <> 1
                """
            )
        ).all()
        if unreconciled:
            raise RuntimeError(
                f"Review migration cardinality failure: {len(unreconciled)} "
                "needs_review signal(s) lack exactly one open case"
            )

        orphaned = conn.execute(
            sa.text(
                """
                SELECT c.id, c.signal_id
                FROM signal_review_cases AS c
                JOIN signals AS s ON s.id = c.signal_id
                WHERE c.status = 'open' AND s.processing_status <> 'needs_review'
                """
            )
        ).all()
        if orphaned:
            raise RuntimeError(
                f"Review migration validation failure: {len(orphaned)} "
                "open case(s) point to non-needs_review signals"
            )


def downgrade() -> None:
    if not op.get_context().as_sql:
        conn = op.get_bind()
        result = (
            conn.execute(
                sa.text(
                    """
                SELECT
                  (SELECT count(*) FROM signal_review_cases) AS review_cases,
                  (SELECT count(*) FROM signals WHERE processing_status = 'dismissed') AS dismissed
                """
                )
            )
            .mappings()
            .one()
        )
        if result["review_cases"] > 0 or result["dismissed"] > 0:
            raise RuntimeError("Cannot downgrade manual review schema after review data exists")

    op.drop_table("signal_review_candidates")
    op.drop_table("signal_review_cases")

    op.drop_constraint("processing_status_values", "signals", type_="check")
    op.create_check_constraint(
        "processing_status_values",
        "signals",
        f"processing_status IN ({_values(PREVIOUS_PROCESSING_STATUSES)})",
    )
