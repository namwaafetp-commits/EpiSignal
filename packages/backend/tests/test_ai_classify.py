"""Tests for the single-model DeepSeek relevance pass."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from episignal_backend.ai.classify import ClassificationResult, run_classification
from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatRequest,
    ChatResponse,
    ClassifiableSignal,
    ModelSpec,
    TokenUsage,
    Verdict,
)
from episignal_backend.ai.ladder import Guards
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.db.types import AiOutcome, AiProvider, AiPurpose

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
FIRST = UUID("b3f1c2d4-0000-4000-8000-000000000001")
SECOND = UUID("b3f1c2d4-0000-4000-8000-000000000002")


def spec() -> ModelSpec:
    return ModelSpec(
        id=uuid4(),
        tier=1,
        model_id="deepseek/deepseek-v4-flash-0731",
        label="DeepSeek V4 Flash",
        provider=AiProvider.OPENROUTER,
        purpose=AiPurpose.CLASSIFICATION,
        prompt_price_per_million=Decimal("0"),
        completion_price_per_million=Decimal("0"),
    )


class FakeRepository:
    def __init__(self, pending: Sequence[ClassifiableSignal]) -> None:
        self.pending = tuple(pending)
        self.requests: list[AiRequestRecord] = []
        self.verdicts: dict[UUID, Verdict] = {}
        self.commits = 0

    def models(self) -> Sequence[ModelSpec]:
        return (spec(),)

    def awaiting_classification(self, *, limit: int) -> Sequence[ClassifiableSignal]:
        return self.pending[:limit]

    def record_request(self, record: AiRequestRecord) -> None:
        self.requests.append(record)

    def record_classification(self, signal_id: UUID, verdict: Verdict) -> None:
        self.verdicts[signal_id] = verdict

    def record_extraction_failure(self, signal_id: UUID) -> None:
        raise AssertionError("relevance rejection is not an extraction failure")

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass


class ScriptedModel:
    def __init__(self, answers: list[object]) -> None:
        self.answers = list(answers)
        self.requests: list[ChatRequest] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return ChatResponse(
            content=str(answer),
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            latency_ms=1,
        )


def signal(identifier: UUID, title: str) -> ClassifiableSignal:
    return ClassifiableSignal(
        id=identifier,
        title=title,
        excerpt="Health officials issued a report.",
        source_name="WHO",
        published_at=NOW,
    )


def answer(relevant: bool, confidence: float) -> str:
    return json.dumps({"relevant": relevant, "confidence": confidence})


def guards() -> Guards:
    return Guards(max_requests=10, max_cost_usd=Decimal("1"))


def test_relevance_uses_one_deepseek_request_per_signal_and_writes_verdicts() -> None:
    repository = FakeRepository(
        (signal(FIRST, "Cholera cases rise"), signal(SECOND, "City wins the cup"))
    )
    model = ScriptedModel([answer(True, 0.91), answer(False, 0.03)])

    result = run_classification(repository, model, guards=guards(), limit=100, now=lambda: NOW)

    assert result == ClassificationResult(examined=2, relevant=1, irrelevant=1, requests=2)
    assert repository.verdicts[FIRST].is_public_health_relevant is True
    assert repository.verdicts[SECOND].is_public_health_relevant is False
    assert [request.model_id for request in model.requests] == [
        "deepseek/deepseek-v4-flash-0731"
    ] * 2
    assert all("disease" not in request.user.lower() for request in model.requests)
    assert all("location" not in request.user.lower() for request in model.requests)


def test_relevance_request_has_only_the_relevance_schema_and_discovery_metadata() -> None:
    repository = FakeRepository((signal(FIRST, "Cholera cases rise"),))
    model = ScriptedModel([answer(True, 0.9)])

    run_classification(repository, model, guards=guards(), now=lambda: NOW)

    request = model.requests[0]
    assert set((request.response_schema or {}).get("properties", {})) == {
        "relevant",
        "confidence",
        "reason_code",
    }
    assert all(slot in request.user for slot in ("TITLE", "SNIPPET", "SOURCE", "PUBLISHED_AT"))


def test_relevance_malformed_response_is_reviewed_without_provider_fallback() -> None:
    repository = FakeRepository((signal(FIRST, "Cholera cases rise"),))
    model = ScriptedModel(["not json"])

    result = run_classification(repository, model, guards=guards(), now=lambda: NOW)

    assert result.reviewed == 1
    assert result.requests == 1
    assert repository.verdicts == {}


def test_relevance_provider_unavailable_leaves_signal_untouched() -> None:
    repository = FakeRepository((signal(FIRST, "Cholera cases rise"),))
    model = ScriptedModel([ModelUnavailable("429")])

    result = run_classification(repository, model, guards=guards(), now=lambda: NOW)

    assert result.unavailable == 1
    assert repository.verdicts == {}
    assert repository.requests[0].outcome is AiOutcome.UNAVAILABLE


def test_relevance_guard_stops_after_the_allowed_request() -> None:
    repository = FakeRepository((signal(FIRST, "a"), signal(SECOND, "b")))
    model = ScriptedModel([answer(True, 0.9), answer(True, 0.9)])

    result = run_classification(
        repository, model, guards=Guards(max_requests=1, max_cost_usd=Decimal("1")), now=lambda: NOW
    )

    assert result.stopped_early is True
    assert SECOND not in repository.verdicts
