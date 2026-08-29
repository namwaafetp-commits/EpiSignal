"""Trailing spend, read from the ledger it happened in.

The monthly figure is always a query against `ai_requests`, never a claim:
every request wrote its cost at the prices in force, so the trailing total is
the ground truth the efficiency target is measured against.

This module imports SQLAlchemy; it reads `ai_requests` and nothing else.
"""

from datetime import datetime, timedelta
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
    cost_usd: Decimal


class SpendSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window_days: int
    since: datetime
    requests: int
    cost_usd: Decimal
    breakdown: tuple[PurposeSpend, ...]


def trailing_spend(
    session: Session, *, window_days: int = DEFAULT_WINDOW_DAYS, now: datetime | None = None
) -> SpendSummary:
    reference = now or datetime.now(tz=None)
    since = reference - timedelta(days=window_days)

    total = session.execute(
        select(func.count(), func.coalesce(func.sum(AiRequest.cost_usd), 0)).where(
            AiRequest.requested_at >= since
        )
    ).one()
    rows = session.execute(
        select(
            AiRequest.model_id,
            AiRequest.purpose,
            AiRequest.outcome,
            func.count(),
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
        cost_usd=Decimal(str(total[1])).quantize(Decimal("0.000001")),
        breakdown=tuple(
            PurposeSpend(
                model_id=model_id,
                purpose=str(purpose),
                outcome=str(outcome),
                requests=count,
                cost_usd=Decimal(str(cost)).quantize(Decimal("0.000001")),
            )
            for model_id, purpose, outcome, count, cost in rows
        ),
    )
