from decimal import Decimal
from uuid import uuid4

import pytest

from episignal_backend.ai.documents import ModelSpec, TokenUsage
from episignal_backend.ai.ladder import Guards, Ladder, RunBudget, cost_usd
from episignal_backend.ai.protocol import NoModelsConfigured


def spec(tier: int, prompt: str = "0", completion: str = "0") -> ModelSpec:
    return ModelSpec(
        id=uuid4(),
        tier=tier,
        model_id=f"vendor/model-tier-{tier}:free",
        label=f"Tier {tier}",
        prompt_price_per_million=Decimal(prompt),
        completion_price_per_million=Decimal(completion),
    )


def test_the_ladder_starts_at_the_lowest_tier() -> None:
    ladder = Ladder.build((spec(3), spec(1), spec(2)), max_tier=3)

    assert [rung.tier for rung in ladder.rungs] == [1, 2, 3]


def test_the_ladder_stops_at_the_configured_maximum() -> None:
    ladder = Ladder.build((spec(1), spec(2), spec(3)), max_tier=2)

    assert [rung.tier for rung in ladder.rungs] == [1, 2]


def test_a_ladder_with_no_rungs_is_refused() -> None:
    with pytest.raises(NoModelsConfigured):
        Ladder.build((), max_tier=3)


def test_two_rows_on_the_same_tier_both_stay_on_the_ladder() -> None:
    ladder = Ladder.build((spec(1), spec(1), spec(2)), max_tier=3)

    assert len(ladder.rungs) == 3


def test_a_free_call_costs_nothing_but_is_still_priced() -> None:
    assert cost_usd(TokenUsage(prompt_tokens=1000, completion_tokens=500), spec(1)) == Decimal("0")


def test_a_priced_call_is_computed_per_million_tokens() -> None:
    priced = spec(2, prompt="0.100000", completion="0.400000")

    amount = cost_usd(TokenUsage(prompt_tokens=1_000_000, completion_tokens=500_000), priced)

    assert amount == Decimal("0.300000")


def test_missing_token_counts_cost_nothing_rather_than_guessing() -> None:
    assert cost_usd(TokenUsage(), spec(2, prompt="1", completion="1")) == Decimal("0")


def test_the_request_guard_stops_a_run_before_the_next_call() -> None:
    budget = RunBudget(Guards(max_requests=2, max_cost_usd=Decimal("1")))

    budget.record(Decimal("0"))
    budget.record(Decimal("0"))

    assert budget.exhausted is True


def test_the_cost_guard_stops_a_run_before_the_next_call() -> None:
    budget = RunBudget(Guards(max_requests=100, max_cost_usd=Decimal("0.10")))

    budget.record(Decimal("0.09"))
    assert budget.exhausted is False

    budget.record(Decimal("0.02"))
    assert budget.exhausted is True


def test_a_fresh_budget_is_not_exhausted() -> None:
    assert RunBudget(Guards(max_requests=1, max_cost_usd=Decimal("1"))).exhausted is False


def test_the_budget_reports_what_it_spent() -> None:
    budget = RunBudget(Guards(max_requests=10, max_cost_usd=Decimal("1")))

    budget.record(Decimal("0.02"))
    budget.record(Decimal("0.03"))

    assert budget.requests == 2
    assert budget.spent == Decimal("0.05")
