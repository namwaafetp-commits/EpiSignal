"""add conservative disease vocabulary updates

The seed file covers fresh databases. This revision applies the same additions
to databases that already contain the reviewed disease vocabulary.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_0021"
down_revision: str | None = "20260901_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO diseases (
                canonical_name, slug, icd10, synonyms, category
            )
            VALUES (
                'Rabies',
                'rabies',
                'A82',
                ARRAY['rabies virus infection']::text[],
                'zoonotic'
            )
            ON CONFLICT (slug) DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE diseases
            SET synonyms = synonyms || ARRAY['West Nile virus']::text[]
            WHERE slug = 'west-nile-virus-disease'
              AND NOT ('West Nile virus' = ANY (synonyms))
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE diseases
            SET synonyms = synonyms || ARRAY['H5 bird flu']::text[]
            WHERE slug = 'avian-influenza'
              AND NOT ('H5 bird flu' = ANY (synonyms))
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError(
        "Cannot downgrade disease vocabulary migration without risking vocabulary data loss"
    )
