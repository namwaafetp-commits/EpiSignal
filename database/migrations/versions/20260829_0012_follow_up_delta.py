"""follow up purpose and observation delta

Revision ID: 20260829_0012
Revises: 20260829_0011
Create Date: 2026-08-29

Two expand steps for the delta pass:

1. `ai_requests.purpose` gains the `follow_up` value. The purpose vocabulary
   is a non-native enum, which is a CHECK constraint, so the constraint is
   replaced with one that admits the new value. Rows already written are
   untouched.
2. `event_observations.delta` becomes a nullable JSONB column holding the
   delta-pass output on exactly the observations a follow-up produced.

The downgrade is explicit about its one lossy step: `follow_up` cost rows are
relabelled `extraction` so the ledger keeps every row and every cent, at the
cost of purpose granularity, and the `delta` column is dropped — its content
exists nowhere else by design, because it is derivable from the two briefs it
compared.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260829_0012"
down_revision: str | None = "20260829_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PURPOSES_UP = ("classification", "extraction", "follow_up")
_PURPOSES_DOWN = ("classification", "extraction")

# The original constraint name is whatever SQLAlchemy generated when the table
# was created, so the drop is located through the catalog rather than guessed.
_DROP_PURPOSE_CHECK = sa.text(
    """
    DO $$
    DECLARE held text;
    BEGIN
        SELECT conname INTO held
        FROM pg_constraint
        WHERE contype = 'c'
          AND conrelid = 'ai_requests'::regclass
          AND pg_get_constraintdef(oid) ILIKE '%purpose%';
        IF held IS NOT NULL THEN
            EXECUTE format('ALTER TABLE ai_requests DROP CONSTRAINT %I', held);
        END IF;
    END $$;
    """
)


def _purpose_check(values: tuple[str, ...]) -> None:
    listed = ", ".join(f"'{value}'" for value in values)
    op.create_check_constraint(
        "ai_purpose_values",
        "ai_requests",
        f"purpose IN ({listed})",
    )


def upgrade() -> None:
    op.execute(_DROP_PURPOSE_CHECK)
    _purpose_check(_PURPOSES_UP)
    op.add_column("event_observations", sa.Column("delta", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("event_observations", "delta")
    op.execute(sa.text("UPDATE ai_requests SET purpose = 'extraction' WHERE purpose = 'follow_up'"))
    op.execute(_DROP_PURPOSE_CHECK)
    _purpose_check(_PURPOSES_DOWN)
