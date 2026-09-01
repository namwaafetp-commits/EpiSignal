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
from episignal_backend.db.types import AiOutcome

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
FIRST = UUID("b3f1c2d4-0000-4000-8000-000000000001")
SECOND = UUID("b3f1c2d4-0000-4000-8000-000000000002")


def spec(tier: int) -> ModelSpec:
    return ModelSpec(
        id=uuid4(),
        tier=tier,
        model_id=f"vendor{tier}/model:free",
        label=f"Tier {tier}",
        prompt_price_per_million=Decimal("0"),
        completion_price_per_million=Decimal("0"),
    )


class FakeRepository:
    def __init__(self, pending: Sequence[ClassifiableSignal]) -> None:
        self._pending = tuple(pending)
        self.requests: list[AiRequestRecord] = []
        self.verdicts: dict[UUID, Verdict] = {}
        self.rejected: list[UUID] = []
        self.commits = 0

    def models(self) -> Sequence[ModelSpec]:
        return (spec(1), spec(2), spec(3))

    def awaiting_classification(self, *, limit: int) -> Sequence[ClassifiableSignal]:
        return self._pending[:limit]

    def record_request(self, record: AiRequestRecord) -> None:
        self.requests.append(record)

    def record_classification(self, signal_id: UUID, verdict: Verdict) -> None:
        self.verdicts[signal_id] = verdict

    def record_extraction_failure(self, signal_id: UUID) -> None:
        self.rejected.append(signal_id)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None


class ScriptedModel:
    def __init__(self, script: list[object]) -> None:
        self.script = script
        self.asked: list[str] = []
        self.requests: list[ChatRequest] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.asked.append(request.model_id)
        self.requests.append(request)
        answer = self.script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return ChatResponse(
            content=str(answer),
            usage=TokenUsage(prompt_tokens=800, completion_tokens=60),
            http_status=200,
            latency_ms=310,
        )


def signal(identifier: UUID, title: str) -> ClassifiableSignal:
    return ClassifiableSignal(id=identifier, title=title, excerpt="Health officials said.")


def answer(*verdicts: dict[str, object]) -> str:
    return json.dumps({"results": list(verdicts)})


def verdict(identifier: UUID, relevant: bool) -> dict[str, object]:
    return {
        "id": str(identifier),
        "relevant": relevant,
        "confidence": 0.91 if relevant else 0.03,
    }


def guards() -> Guards:
    return Guards(max_requests=50, max_cost_usd=Decimal("1"))


def test_a_relevant_and_an_irrelevant_signal_are_both_decided() -> None:
    repository = FakeRepository(
        (signal(FIRST, "Cholera cases rise"), signal(SECOND, "City wins the cup"))
    )
    model = ScriptedModel([answer(verdict(FIRST, True), verdict(SECOND, False))])

    result = run_classification(
        repository, model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    assert result == ClassificationResult(
        examined=2, relevant=1, irrelevant=1, reviewed=0, unavailable=0, requests=1
    )
    assert repository.verdicts[FIRST].is_public_health_relevant is True
    assert repository.verdicts[SECOND].is_public_health_relevant is False


def test_an_id_that_was_never_sent_escalates_the_whole_batch() -> None:
    repository = FakeRepository((signal(FIRST, "Cholera cases rise"),))
    model = ScriptedModel([answer(verdict(uuid4(), True)), answer(verdict(FIRST, True))])

    run_classification(
        repository, model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    assert len(model.asked) == 2
    assert repository.verdicts[FIRST].is_public_health_relevant is True


def test_rejection_at_every_tier_marks_the_whole_batch_failed() -> None:
    repository = FakeRepository((signal(FIRST, "a"), signal(SECOND, "b")))
    model = ScriptedModel(["nonsense", "nonsense", "nonsense"])

    result = run_classification(
        repository, model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    assert repository.rejected == []
    assert result.reviewed == 2


def test_schema_rejection_leaves_signal_eligible_for_a_later_classification() -> None:
    repository = FakeRepository((signal(FIRST, "Cholera cases rise"),))
    failed_model = ScriptedModel(["nonsense", "nonsense", "nonsense"])

    run_classification(
        repository, failed_model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    retry_model = ScriptedModel([answer(verdict(FIRST, True))])
    run_classification(
        repository, retry_model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    assert repository.verdicts[FIRST].is_public_health_relevant is True


def test_classification_requests_use_strict_structured_output() -> None:
    repository = FakeRepository((signal(FIRST, "Cholera cases rise"),))
    model = ScriptedModel([answer(verdict(FIRST, True))])

    run_classification(
        repository, model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    request = model.requests[0]
    from episignal_backend.ai.schema import classification_json_schema

    assert request.response_schema == classification_json_schema()
    assert request.schema_name == "classification_response"
    assert request.temperature == 0.0


def test_an_unreachable_provider_leaves_the_signals_untouched() -> None:
    repository = FakeRepository((signal(FIRST, "a"),))
    model = ScriptedModel(
        [ModelUnavailable("429"), ModelUnavailable("429"), ModelUnavailable("429")]
    )

    run_classification(
        repository, model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    assert repository.verdicts == {}
    assert repository.rejected == []


def test_every_attempt_writes_a_cost_row_naming_the_batch_size() -> None:
    repository = FakeRepository((signal(FIRST, "a"), signal(SECOND, "b")))
    model = ScriptedModel(["nonsense", answer(verdict(FIRST, True), verdict(SECOND, True))])

    run_classification(
        repository, model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    assert [record.outcome for record in repository.requests] == [
        AiOutcome.REJECTED,
        AiOutcome.ACCEPTED,
    ]
    assert {record.batch_size for record in repository.requests} == {2}
    assert all(record.signal_id is None for record in repository.requests)


def test_the_batch_size_splits_the_queue_into_separate_requests() -> None:
    repository = FakeRepository((signal(FIRST, "a"), signal(SECOND, "b")))
    model = ScriptedModel([answer(verdict(FIRST, True)), answer(verdict(SECOND, True))])

    result = run_classification(
        repository, model, guards=guards(), batch_size=1, limit=100, now=lambda: NOW
    )

    assert result.requests == 2
    assert len(model.asked) == 2


def test_a_reached_request_guard_stops_the_pass_and_reports_it() -> None:
    repository = FakeRepository((signal(FIRST, "a"), signal(SECOND, "b")))
    model = ScriptedModel([answer(verdict(FIRST, True))])

    result = run_classification(
        repository,
        model,
        guards=Guards(max_requests=1, max_cost_usd=Decimal("1")),
        batch_size=1,
        limit=100,
        now=lambda: NOW,
    )

    assert result.stopped_early is True
    assert SECOND not in repository.verdicts


def test_an_empty_queue_makes_no_request() -> None:
    repository = FakeRepository(())
    model = ScriptedModel([])

    result = run_classification(
        repository, model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    assert result.examined == 0
    assert model.asked == []
