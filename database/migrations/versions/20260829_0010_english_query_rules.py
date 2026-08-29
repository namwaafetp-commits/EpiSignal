"""english query rules

Revision ID: 20260829_0010
Revises: 20260828_0009
Create Date: 2026-08-29

Pins the GDELT query library to English for Phase 1. The seed file now writes
every rule with `language = 'en'`; because the natural key is
`(query, language)`, reseeding inserts new English rows rather than updating
the existing unrestricted ones. This revision deactivates those unrestricted
rows so a query is never served by both an English row and an `any` row at
once. No row is deleted: the downgrade reactivates the unrestricted rows, and
Phase 2 multilingual ingestion is that reactivation plus a seed change.

Idempotent by construction: running it twice finds the same rows already
inactive, and running it before the English rows are seeded deactivates
nothing because the existence condition fails.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0010"
down_revision: str | None = "20260828_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEACTIVATE = sa.text(
    """
    UPDATE gdelt_query_rules AS unrestricted
    SET active = false
    WHERE unrestricted.language = 'any'
      AND unrestricted.active
      AND EXISTS (
          SELECT 1 FROM gdelt_query_rules AS english
          WHERE english.query = unrestricted.query
            AND english.language = 'en'
      )
    """
)

_REACTIVATE = sa.text(
    """
    UPDATE gdelt_query_rules AS unrestricted
    SET active = true
    WHERE unrestricted.language = 'any'
      AND NOT unrestricted.active
      AND EXISTS (
          SELECT 1 FROM gdelt_query_rules AS english
          WHERE english.query = unrestricted.query
            AND english.language = 'en'
      )
    """
)


def upgrade() -> None:
    op.execute(_DEACTIVATE)


def downgrade() -> None:
    op.execute(_REACTIVATE)
