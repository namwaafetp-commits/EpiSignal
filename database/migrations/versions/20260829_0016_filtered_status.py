"""filtered processing status

Revision ID: 20260829_0016
Revises: 20260829_0015
Create Date: 2026-08-29

The keyword gate needs a terminal status that preserves the row:
- Expand the processing_status check constraint with 'filtered'.
- Downgrade returns filtered rows to 'fetched' before narrowing the
  constraint, so no evidence is lost and the funnel simply re-gates them.

processing_status is a VARCHAR with a CHECK constraint, not a pg enum:
db/types.vocabulary() builds sa.Enum(..., native_enum=False,
create_constraint=True). ALTER TYPE would fail here.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260829_0016"
down_revision: str | None = "20260829_0015"
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
    "filtered",
)

PREVIOUS_PROCESSING_STATUSES = tuple(
    status for status in PROCESSING_STATUSES if status != "filtered"
)


def _values(statuses: tuple[str, ...]) -> str:
    return ", ".join(f"'{status}'" for status in statuses)


def upgrade() -> None:
    op.drop_constraint("processing_status_values", "signals", type_="check")
    op.create_check_constraint(
        "processing_status_values",
        "signals",
        f"processing_status IN ({_values(PROCESSING_STATUSES)})",
    )


def downgrade() -> None:
    # Returned to the funnel rather than refused or deleted: a filtered row is
    # a kept article the gate declined, so the honest reverse of the gate is
    # the state the article had before it ran.
    op.execute("UPDATE signals SET processing_status = 'fetched' WHERE processing_status = 'filtered'")
    op.drop_constraint("processing_status_values", "signals", type_="check")
    op.create_check_constraint(
        "processing_status_values",
        "signals",
        f"processing_status IN ({_values(PREVIOUS_PROCESSING_STATUSES)})",
    )
