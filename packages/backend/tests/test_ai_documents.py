from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatRequest,
    ChatResponse,
    ClassifiableSignal,
    ExtractableSignal,
    ModelSpec,
    TokenUsage,
)
from episignal_backend.db.types import AiOutcome, AiPurpose
from pydantic import ValidationError

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


def test_a_model_spec_carries_its_tier_and_its_prices() -> None:
    spec = ModelSpec(
        id=uuid4(),
        tier=1,
        model_id="meta-llama/llama-3.3-70b-instruct:free",
        label="Llama 3.3 70B (free)",
        prompt_price_per_million=Decimal("0"),
        completion_price_per_million=Decimal("0"),
    )

    assert spec.tier == 1
    assert spec.prompt_price_per_million == Decimal("0")


def test_a_tier_outside_the_ladder_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelSpec(
            id=uuid4(),
            tier=0,
            model_id="x",
            label="x",
            prompt_price_per_million=Decimal("0"),
            completion_price_per_million=Decimal("0"),
        )


def test_a_negative_price_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelSpec(
            id=uuid4(),
            tier=1,
            model_id="x",
            label="x",
            prompt_price_per_million=Decimal("-1"),
            completion_price_per_million=Decimal("0"),
        )


def test_a_classifiable_signal_must_carry_text() -> None:
    with pytest.raises(ValidationError):
        ClassifiableSignal(id=uuid4(), title="Measles cases rise", excerpt="   ")


def test_an_extractable_signal_must_carry_text() -> None:
    with pytest.raises(ValidationError):
        ExtractableSignal(id=uuid4(), title="Measles cases rise", raw_text="")


def test_a_chat_response_records_what_the_call_cost_in_tokens_and_time() -> None:
    response = ChatResponse(
        content='{"results": []}',
        usage=TokenUsage(prompt_tokens=1200, completion_tokens=90),
        http_status=200,
        latency_ms=830,
    )

    assert response.usage.prompt_tokens == 1200
    assert response.latency_ms == 830


def test_a_chat_request_names_the_model_it_is_for() -> None:
    request = ChatRequest(
        model_id="meta-llama/llama-3.3-70b-instruct:free",
        system="You extract facts.",
        user="Article text.",
    )

    assert request.model_id.endswith(":free")


def test_a_cost_row_can_describe_a_call_that_never_answered() -> None:
    record = AiRequestRecord(
        ai_model_id=uuid4(),
        model_id="meta-llama/llama-3.3-70b-instruct:free",
        tier=1,
        purpose=AiPurpose.EXTRACTION,
        signal_id=uuid4(),
        batch_size=1,
        prompt_tokens=None,
        completion_tokens=None,
        latency_ms=15000,
        http_status=None,
        outcome=AiOutcome.UNAVAILABLE,
        rejection_reason="timeout",
        prompt_price_per_million=Decimal("0"),
        completion_price_per_million=Decimal("0"),
        cost_usd=Decimal("0"),
        requested_at=NOW,
    )

    assert record.outcome is AiOutcome.UNAVAILABLE
    assert record.prompt_tokens is None


def test_a_cost_row_requires_an_aware_timestamp() -> None:
    with pytest.raises(ValidationError):
        AiRequestRecord(
            ai_model_id=uuid4(),
            model_id="x",
            tier=1,
            purpose=AiPurpose.CLASSIFICATION,
            signal_id=None,
            batch_size=20,
            prompt_tokens=10,
            completion_tokens=10,
            latency_ms=100,
            http_status=200,
            outcome=AiOutcome.ACCEPTED,
            rejection_reason=None,
            prompt_price_per_million=Decimal("0"),
            completion_price_per_million=Decimal("0"),
            cost_usd=Decimal("0"),
            requested_at=datetime(2026, 8, 27, 9, 0),
        )
