import json
from decimal import Decimal
from uuid import uuid4

from episignal_backend.ai.documents import ChatResponse, ModelSpec, TokenUsage
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.ai.schema import BriefPoint, BriefSlot
from episignal_backend.db.types import AiOutcome, AiProvider
from episignal_backend.events.delta import (
    DeltaOutcome,
    delta_payload,
    run_delta,
)

BRIEF = (
    BriefPoint(slot=BriefSlot.WHAT_WHERE, text="Cholera in Sana'a", reported=True),
    BriefPoint(slot=BriefSlot.COUNTS, text="No counts", reported=False),
    BriefPoint(slot=BriefSlot.TIMING, text="This week", reported=True),
    BriefPoint(slot=BriefSlot.SPREAD, text="No spread", reported=False),
    BriefPoint(slot=BriefSlot.REPORTING, text="Ministry of Health", reported=True),
)

UPDATED = json.dumps(
    {
        "brief": [
            {"slot": "what_where", "text": "Cholera in Sana'a", "reported": True},
            {"slot": "counts", "text": "Cases rose to 400", "reported": True},
            {"slot": "timing", "text": "This week", "reported": True},
            {"slot": "spread", "text": "No spread", "reported": False},
            {"slot": "reporting", "text": "Ministry of Health", "reported": True},
        ],
        "what_changed": "Counts updated from unreported to 400.",
    }
)


def spec() -> ModelSpec:
    return ModelSpec(
        id=uuid4(),
        tier=1,
        model_id="google/gemini-2.5-flash-lite",
        label="Gemini 2.5 Flash-Lite",
        provider=AiProvider.GEMINI,
        prompt_price_per_million=Decimal("0.10"),
        completion_price_per_million=Decimal("0.40"),
    )


class FakeModel:
    def __init__(self, content: str | None, refuse: bool = False) -> None:
        self._content = content
        self._refuse = refuse

    def complete(self, request) -> ChatResponse:
        if self._refuse:
            raise ModelUnavailable("quota")
        return ChatResponse(
            content=self._content or "",
            usage=TokenUsage(prompt_tokens=300, completion_tokens=80),
            latency_ms=12,
        )


def test_an_accepted_delta_carries_brief_change_and_cost_facts() -> None:
    result = run_delta(FakeModel(UPDATED), spec(), previous=BRIEF, new=BRIEF)

    assert result.outcome is DeltaOutcome.ACCEPTED
    assert result.delta is not None
    assert result.delta.what_changed.startswith("Counts updated")
    assert [point.slot for point in result.delta.brief] == [point.slot for point in BRIEF]
    assert result.attempt is not None
    assert result.attempt.outcome is AiOutcome.ACCEPTED
    assert result.attempt.usage.prompt_tokens == 300
    # 300 prompt tokens at 0.10 per million plus 80 completion at 0.40.
    assert result.attempt.cost == Decimal("0.0000620")


def test_an_unavailable_model_is_reported_not_raised() -> None:
    result = run_delta(FakeModel(None, refuse=True), spec(), previous=BRIEF, new=BRIEF)

    assert result.outcome is DeltaOutcome.UNAVAILABLE
    assert result.delta is None
    assert result.attempt is not None
    assert result.attempt.outcome is AiOutcome.UNAVAILABLE
    assert result.attempt.cost == Decimal("0")


def test_a_schema_violating_answer_is_unavailable_and_costed() -> None:
    wrong = json.dumps(
        {
            "brief": [
                {"slot": "counts", "text": "400 cases", "reported": True},
            ],
            "what_changed": "slots out of order and incomplete",
        }
    )
    result = run_delta(FakeModel(wrong), spec(), previous=BRIEF, new=BRIEF)

    assert result.outcome is DeltaOutcome.UNAVAILABLE
    assert result.attempt is not None
    assert result.attempt.outcome is AiOutcome.REJECTED
    assert result.attempt.usage.prompt_tokens == 300


def test_delta_payload_holds_the_change_and_the_updated_brief() -> None:
    result = run_delta(FakeModel(UPDATED), spec(), previous=BRIEF, new=BRIEF)
    assert result.delta is not None

    payload = delta_payload(result.delta)

    assert payload["what_changed"].startswith("Counts updated")
    brief = payload["brief"]
    assert [point["slot"] for point in brief] == [slot.value for slot in BriefSlot]


def test_the_request_asks_for_zero_temperature_and_a_schema() -> None:
    seen: list[object] = []

    class RecordingModel(FakeModel):
        def complete(self, request) -> ChatResponse:
            seen.append(request)
            return super().complete(request)

    run_delta(RecordingModel(UPDATED), spec(), previous=BRIEF, new=BRIEF)

    request = seen[0]
    assert request.temperature == 0.0
    assert request.schema_name == "event_delta"
    assert request.response_schema is not None
    assert "what_where" in json.dumps(request.response_schema)
