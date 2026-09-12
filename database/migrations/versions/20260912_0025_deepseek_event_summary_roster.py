"""activate the DeepSeek event-summary roster route

The event-summary route changed from the retired Mistral model to the DeepSeek
model in application code, but the roster is database-owned.  This revision
reconciles existing databases so a normal migration reaches the same state as
the reviewed seed file.

The model row is shared by the classification and event-summary routes.  The
``purpose`` value records the current summary rollout while the registry keeps
the two final passes on the same physical model row.  AI request history is
left untouched; retiring a model only changes its active roster state.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260912_0025"
down_revision: str | None = "20260911_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    # Keep the historical row for request-ledger traceability, but prevent the
    # old route from remaining an active candidate after this revision.
    op.execute(
        sa.text(
            """
            UPDATE ai_models
            SET active = false, updated_at = now()
            WHERE model_id = 'mistralai/mistral-small-3.2-24b-instruct'
            """
        )
    )

    # The unique model_id constraint makes this safe for both an empty fresh
    # roster and an existing roster containing an older DeepSeek classification
    # row.  Every mutable roster fact is written explicitly so rerunning the
    # seed after migration cannot drift the active route.
    op.execute(
        sa.text(
            """
            INSERT INTO ai_models (
                tier,
                model_id,
                label,
                provider,
                purpose,
                prompt_price_per_million,
                completion_price_per_million,
                active
            )
            VALUES (
                1,
                'deepseek/deepseek-v4-flash-0731',
                'DeepSeek V4 Flash',
                'openrouter',
                'event_summary',
                0.03,
                0.10,
                true
            )
            ON CONFLICT (model_id) DO UPDATE SET
                tier = EXCLUDED.tier,
                label = EXCLUDED.label,
                provider = EXCLUDED.provider,
                purpose = EXCLUDED.purpose,
                prompt_price_per_million = EXCLUDED.prompt_price_per_million,
                completion_price_per_million = EXCLUDED.completion_price_per_million,
                active = EXCLUDED.active,
                updated_at = now()
            """
        )
    )


def downgrade() -> None:
    # Restore the prior route without deleting either model row or changing any
    # request/event history.  The target row may have existed before this
    # revision as the classification row, so retaining it is the safe rollback
    # behavior for a data migration.
    op.execute(
        sa.text(
            """
            UPDATE ai_models
            SET active = true,
                purpose = 'classification',
                updated_at = now()
            WHERE model_id = 'deepseek/deepseek-v4-flash-0731'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE ai_models
            SET active = true, purpose = 'event_summary', updated_at = now()
            WHERE model_id = 'mistralai/mistral-small-3.2-24b-instruct'
            """
        )
    )
