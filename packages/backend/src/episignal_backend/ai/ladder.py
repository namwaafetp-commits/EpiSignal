"""Which model to ask next, whether the run may ask at all, and what it cost.

Pure arithmetic and ordering. Nothing here performs a request; the passes do
that, and hand the outcome back so the budget stays the single place that knows
how much of the run remains.

This module imports neither SQLAlchemy nor httpx.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from episignal_backend.ai.documents import ModelSpec, TokenUsage
from episignal_backend.ai.protocol import NoModelsConfigured

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
