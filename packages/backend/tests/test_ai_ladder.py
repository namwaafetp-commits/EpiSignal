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


from episignal_backend.ai.documents import ChatRequest, ChatResponse
from episignal_backend.ai.ladder import Attempt, ClimbOutcome, climb
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.ai.validate import RejectionReason, Rejected


class ScriptedModel:
    """Answers from a script, one entry per call, so a climb is reproducible."""

    def __init__(self, script: list[object]) -> None:
        self.script = script
        self.asked: list[str] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.asked.append(request.model_id)
        answer = self.script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return ChatResponse(
            content=str(answer), usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
            http_status=200, latency_ms=5,
        )


def request_for(spec: ModelSpec) -> ChatRequest:
    return ChatRequest(model_id=spec.model_id, system="s", user="u")


def accept_ok(content: str) -> str:
    if content != "ok":
        raise Rejected(RejectionReason.SHAPE, content)
    return content


def budget() -> RunBudget:
    return RunBudget(Guards(max_requests=10, max_cost_usd=Decimal("1")))


def test_a_good_answer_at_the_first_tier_makes_one_request() -> None:
    model = ScriptedModel(["ok"])
    recorded: list[Attempt] = []

    result = climb(
        ladder=Ladder.build((spec(1), spec(2), spec(3)), max_tier=3),
        budget=budget(),
        model=model,
        request_for=request_for,
        accept=accept_ok,
        on_attempt=recorded.append,
    )

    assert result.outcome is ClimbOutcome.ACCEPTED
    assert result.value == "ok"
    assert len(model.asked) == 1
    assert len(recorded) == 1


def test_a_rejected_answer_escalates_to_the_next_tier() -> None:
    model = ScriptedModel(["bad", "ok"])

    result = climb(
        ladder=Ladder.build((spec(1), spec(2), spec(3)), max_tier=3),
        budget=budget(),
        model=model,
        request_for=request_for,
        accept=accept_ok,
        on_attempt=lambda attempt: None,
    )

    assert result.outcome is ClimbOutcome.ACCEPTED
    assert model.asked == ["vendor/model-tier-1:free", "vendor/model-tier-2:free"]


def test_rejection_at_every_tier_ends_the_climb_as_rejected() -> None:
    model = ScriptedModel(["bad", "bad", "bad"])

    result = climb(
        ladder=Ladder.build((spec(1), spec(2), spec(3)), max_tier=3),
        budget=budget(),
        model=model,
        request_for=request_for,
        accept=accept_ok,
        on_attempt=lambda attempt: None,
    )

    assert result.outcome is ClimbOutcome.REJECTED
    assert result.reason == RejectionReason.SHAPE.value
    assert len(model.asked) == 3


def test_an_unreachable_provider_at_every_tier_is_not_a_rejection() -> None:
    model = ScriptedModel([ModelUnavailable("429"), ModelUnavailable("429")])

    result = climb(
        ladder=Ladder.build((spec(1), spec(2)), max_tier=3),
        budget=budget(),
        model=model,
        request_for=request_for,
        accept=accept_ok,
        on_attempt=lambda attempt: None,
    )

    assert result.outcome is ClimbOutcome.UNAVAILABLE


def test_a_climb_records_a_cost_row_for_every_attempt_including_failures() -> None:
    model = ScriptedModel(["bad", ModelUnavailable("429"), "ok"])
    recorded: list[Attempt] = []

    climb(
        ladder=Ladder.build((spec(1), spec(2), spec(3)), max_tier=3),
        budget=budget(),
        model=model,
        request_for=request_for,
        accept=accept_ok,
        on_attempt=recorded.append,
    )

    assert [attempt.outcome.value for attempt in recorded] == [
        "rejected",
        "unavailable",
        "accepted",
    ]


def test_an_exhausted_budget_stops_the_climb_before_it_starts() -> None:
    model = ScriptedModel(["ok"])
    spent = RunBudget(Guards(max_requests=1, max_cost_usd=Decimal("1")))
    spent.record(Decimal("0"))

    result = climb(
        ladder=Ladder.build((spec(1),), max_tier=3),
        budget=spent,
        model=model,
        request_for=request_for,
        accept=accept_ok,
        on_attempt=lambda attempt: None,
    )

    assert result.outcome is ClimbOutcome.GUARD
    assert model.asked == []


def test_the_language_of_the_document_never_appears_in_the_climb() -> None:
    import inspect

    from episignal_backend.ai import ladder as module

    source = inspect.getsource(module)

    assert "language" not in source
    assert "script" not in source

