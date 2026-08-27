"""Which model to ask next, whether the run may ask at all, and what it cost.

Pure arithmetic and ordering. Nothing here performs a request; the passes do
that, and hand the outcome back so the budget stays the single place that knows
how much of the run remains.

This module imports neither SQLAlchemy nor httpx.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID

from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatRequest,
    ModelSpec,
    TokenUsage,
)
from episignal_backend.ai.protocol import ChatModel, ModelUnavailable, NoModelsConfigured
from episignal_backend.ai.validate import Rejected
from episignal_backend.db.types import AiOutcome, AiPurpose

PER_MILLION = Decimal(1_000_000)
COST_PLACES = Decimal("0.000001")


def cost_usd(usage: TokenUsage, spec: ModelSpec) -> Decimal:
    """Computed from the roster's prices, never from what the provider reports.

    A provider-reported cost is a number we cannot reproduce and cannot audit. A
    missing token count contributes nothing rather than an estimate, because an
    invented number in a ledger is worse than a gap in one.
    """
    prompt = Decimal(usage.prompt_tokens or 0) * spec.prompt_price_per_million
    completion = Decimal(usage.completion_tokens or 0) * spec.completion_price_per_million
    return ((prompt + completion) / PER_MILLION).quantize(COST_PLACES)


@dataclass(frozen=True)
class Guards:
    """What stops a run. Requests bind first under a free ladder; cost binds
    first once a paid rung exists."""

    max_requests: int
    max_cost_usd: Decimal


@dataclass
class RunBudget:
    guards: Guards
    requests: int = 0
    spent: Decimal = field(default=Decimal("0"))

    def record(self, amount: Decimal) -> None:
        self.requests += 1
        self.spent += amount

    @property
    def exhausted(self) -> bool:
        return self.requests >= self.guards.max_requests or self.spent >= self.guards.max_cost_usd


@dataclass(frozen=True)
class Ladder:
    """The rungs, lowest tier first."""

    rungs: tuple[ModelSpec, ...]

    @classmethod
    def build(cls, specs: Sequence[ModelSpec], *, max_tier: int) -> "Ladder":
        # Sorted by tier then model id: a stable order matters because two rows
        # may share a tier, and a run that climbs in a different order each time
        # cannot be compared with the previous one.
        rungs = tuple(
            sorted(
                (spec for spec in specs if spec.tier <= max_tier),
                key=lambda spec: (spec.tier, spec.model_id),
            )
        )
        if not rungs:
            raise NoModelsConfigured("no active model at or below the configured maximum tier")
        return cls(rungs=rungs)


T = TypeVar("T")


class ClimbOutcome(StrEnum):
    ACCEPTED = "accepted"
    # Every tier answered and no answer could be trusted. The signal is now
    # known to be beyond this ladder, so it goes for review.
    REJECTED = "rejected"
    # No tier answered. Nothing is known about the signal, so it must be left
    # exactly as it was and tried again later.
    UNAVAILABLE = "unavailable"
    GUARD = "guard"


@dataclass(frozen=True)
class Attempt:
    """One request, as the cost row will describe it."""

    spec: ModelSpec
    usage: TokenUsage
    http_status: int | None
    latency_ms: int
    outcome: AiOutcome
    reason: str | None
    cost: Decimal


@dataclass(frozen=True)
class ClimbResult(Generic[T]):
    outcome: ClimbOutcome
    value: T | None = None
    reason: str | None = None


def climb(
    *,
    ladder: Ladder,
    budget: RunBudget,
    model: ChatModel,
    request_for: Callable[[ModelSpec], ChatRequest],
    accept: Callable[[str], T],
    on_attempt: Callable[[Attempt], None],
) -> ClimbResult[T]:
    """Ask each rung in turn until one answer passes `accept`.

    `accept` raises `Rejected`; the provider raises `ModelUnavailable`. The two
    are kept apart all the way out, because one means the answer was wrong and
    the other means there was no answer.
    """
    reason: str | None = None
    answered = False

    for spec in ladder.rungs:
        if budget.exhausted:
            return ClimbResult(outcome=ClimbOutcome.GUARD, reason=reason)

        try:
            response = model.complete(request_for(spec))
        except ModelUnavailable as error:
            reason = str(error)
            budget.record(Decimal("0"))
            on_attempt(
                Attempt(
                    spec=spec,
                    usage=TokenUsage(),
                    http_status=None,
                    latency_ms=0,
                    outcome=AiOutcome.UNAVAILABLE,
                    reason=reason,
                    cost=Decimal("0"),
                )
            )
            continue

        answered = True
        amount = cost_usd(response.usage, spec)
        budget.record(amount)

        try:
            value = accept(response.content)
        except Rejected as rejection:
            reason = rejection.reason.value
            on_attempt(
                Attempt(
                    spec=spec,
                    usage=response.usage,
                    http_status=response.http_status,
                    latency_ms=response.latency_ms,
                    outcome=AiOutcome.REJECTED,
                    reason=reason,
                    cost=amount,
                )
            )
            continue

        on_attempt(
            Attempt(
                spec=spec,
                usage=response.usage,
                http_status=response.http_status,
                latency_ms=response.latency_ms,
                outcome=AiOutcome.ACCEPTED,
                reason=None,
                cost=amount,
            )
        )
        return ClimbResult(outcome=ClimbOutcome.ACCEPTED, value=value)

    ending = ClimbOutcome.REJECTED if answered else ClimbOutcome.UNAVAILABLE
    return ClimbResult(outcome=ending, reason=reason)


def cost_row(
    attempt: Attempt,
    *,
    purpose: AiPurpose,
    signal_id: UUID | None,
    batch_size: int,
    at: datetime,
) -> AiRequestRecord:
    """One attempt, as the ledger records it.

    Shared by both passes on purpose: two passes that each wrote their own cost
    row would eventually record different things about the same event, and the
    ledger would stop being comparable with itself.
    """
    return AiRequestRecord(
        ai_model_id=attempt.spec.id,
        model_id=attempt.spec.model_id,
        tier=attempt.spec.tier,
        purpose=purpose,
        signal_id=signal_id,
        batch_size=batch_size,
        prompt_tokens=attempt.usage.prompt_tokens,
        completion_tokens=attempt.usage.completion_tokens,
        latency_ms=attempt.latency_ms,
        http_status=attempt.http_status,
        outcome=attempt.outcome,
        rejection_reason=attempt.reason,
        prompt_price_per_million=attempt.spec.prompt_price_per_million,
        completion_price_per_million=attempt.spec.completion_price_per_million,
        cost_usd=attempt.cost,
        requested_at=at,
    )

