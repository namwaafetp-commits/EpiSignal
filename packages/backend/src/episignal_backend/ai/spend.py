"""Trailing spend, read from the ledger it happened in.

The monthly figure is always a query against `ai_requests`, never a claim:
every request wrote its cost at the prices in force, so the trailing total is
the ground truth the efficiency target is measured against.

This module imports SQLAlchemy; it reads `ai_requests` and nothing else.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from episignal_backend.models import AiRequest

DEFAULT_WINDOW_DAYS = 30


class PurposeSpend(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str
    purpose: str
    outcome: str
    requests: int
    signals: int
    cost_usd: Decimal


class SpendSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window_days: int
    since: datetime
    requests: int
    signals: int
    cost_usd: Decimal
    breakdown: tuple[PurposeSpend, ...]


def trailing_spend(
    session: Session, *, window_days: int = DEFAULT_WINDOW_DAYS, now: datetime | None = None
) -> SpendSummary:
    # The ledger stores timestamptz, so the window is cut on the UTC clock; a
    # naive local clock would skew the trailing month by the host's offset.
    reference = now or datetime.now(UTC)
    since = reference - timedelta(days=window_days)

    total = session.execute(
        select(
            func.count(),
            func.coalesce(func.sum(AiRequest.batch_size), 0),
            func.coalesce(func.sum(AiRequest.cost_usd), 0),
        ).where(AiRequest.requested_at >= since)
    ).one()
    rows = session.execute(
        select(
            AiRequest.model_id,
            AiRequest.purpose,
            AiRequest.outcome,
            func.count(),
            func.coalesce(func.sum(AiRequest.batch_size), 0),
            func.coalesce(func.sum(AiRequest.cost_usd), 0),
        )
        .where(AiRequest.requested_at >= since)
        .group_by(AiRequest.model_id, AiRequest.purpose, AiRequest.outcome)
        .order_by(func.sum(AiRequest.cost_usd).desc())
    ).all()

    return SpendSummary(
        window_days=window_days,
        since=since,
        requests=total[0],
        signals=total[1],
        cost_usd=Decimal(str(total[2])).quantize(Decimal("0.000001")),
        breakdown=tuple(
            PurposeSpend(
                model_id=model_id,
                purpose=str(purpose),
                outcome=str(outcome),
                requests=count,
                signals=signals_count,
                cost_usd=Decimal(str(cost)).quantize(Decimal("0.000001")),
            )
            for model_id, purpose, outcome, count, signals_count, cost in rows
        ),
    )
