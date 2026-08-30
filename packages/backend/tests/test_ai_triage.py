import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatRequest,
    ChatResponse,
    ModelSpec,
    TokenUsage,
    TriageableSignal,
)
from episignal_backend.ai.ladder import Guards
from episignal_backend.ai.schema import TriageVerdict
from episignal_backend.ai.triage import TriageResult, run_triage
from episignal_backend.db.types import AiOutcome, AiPurpose, TriageStatus

NOW = datetime(2026, 8, 30, 9, 0, tzinfo=UTC)
DENGUE_ID = UUID("b3f1c2d4-0000-4000-8000-000000000010")


def signal(title: str = "Dengue outbreak in Chiang Mai") -> TriageableSignal:
    return TriageableSignal(
        id=uuid4(),
        title=title,
        excerpt="Officials reported 42 dengue cases in Chiang Mai province.",
        source_name="Bangkok Post",
        url="https://example.com/dengue",
        published_at=NOW,
        language="en",
    )


SIGNAL = signal()
SECOND = signal("Dengue surveillance update")
GOOD_TRIAGE = json.dumps(
    {
        "relevant": True,
        "public_health": True,
        "category": "infectious_disease",
        "event_type": "outbreak_report",
        "disease": "dengue",
        "country": "TH",
        "admin1": "Chiang Mai",
        "admin2": None,
        "location_text": "Chiang Mai province",
        "confidence": 0.93,
    }
)
IRRELEVANT_TRIAGE = json.dumps(
    {
        "relevant": False,
        "public_health": False,
        "category": "not_public_health",
        "confidence": 0.98,
    }
)
MALFORMED = json.dumps({"relevant": "maybe"})


def model_spec() -> ModelSpec:
    return ModelSpec(
        id=uuid4(),
        tier=1,
        model_id="meta-llama/llama-3.1-8b-instruct",
        label="Llama 3.1 8B Instruct",
        purpose=AiPurpose.TRIAGE,
        prompt_price_per_million=Decimal("0.02"),
        completion_price_per_million=Decimal("0.04"),
    )


@dataclass(frozen=True)
class StoredTriage:
    disease: str | None
    disease_id: UUID | None


class TriageRepository:
    def __init__(
        self,
        *,
        pending: Sequence[TriageableSignal],
        diseases: dict[str, UUID] | None = None,
    ) -> None:
        self.pending = tuple(pending)
        self.diseases = diseases or {}
        self.requests: list[AiRequestRecord] = []
        self.stored: dict[UUID, StoredTriage] = {}
        self.statuses: dict[UUID, TriageStatus] = {
            item.id: TriageStatus.PENDING for item in pending
        }
        self.filtered: list[UUID] = []
        self.deleted: list[UUID] = []
        self.commits = 0

    def models(self) -> Sequence[ModelSpec]:
        return (model_spec(),)

    def awaiting_triage(self, *, limit: int) -> Sequence[TriageableSignal]:
        return self.pending[:limit]

    def resolve_disease(self, name: str) -> UUID | None:
        return self.diseases.get(name.casefold())

    def record_request(self, record: AiRequestRecord) -> None:
        self.requests.append(record)

    def record_triage(
        self,
        signal_id: UUID,
        verdict: TriageVerdict,
        disease_id: UUID | None,
        at: datetime,
    ) -> None:
        del at
        self.stored[signal_id] = StoredTriage(
            disease=verdict.disease,
            disease_id=disease_id,
        )
        self.statuses[signal_id] = TriageStatus.DONE
        if not verdict.relevant:
            self.filtered.append(signal_id)

    def record_triage_failure(self, signal_id: UUID) -> None:
        self.statuses[signal_id] = TriageStatus.FAILED

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None


class ScriptedModel:
    def __init__(self, script: list[ChatResponse]) -> None:
        self.script = script
        self.requests: list[ChatRequest] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return self.script.pop(0)


def response(content: str) -> ChatResponse:
    return ChatResponse(
        content=content,
        usage=TokenUsage(prompt_tokens=400, completion_tokens=80),
        http_status=200,
        latency_ms=10,
    )


def guards() -> Guards:
    return Guards(max_requests=20, max_cost_usd=Decimal("1"))


def test_a_valid_answer_is_stored_and_costed() -> None:
    repository = TriageRepository(pending=(SIGNAL,))
    model = ScriptedModel([response(GOOD_TRIAGE)])

    result = run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert result.triaged == 1
    assert result.repaired == 0
    assert repository.stored[SIGNAL.id].disease == "dengue"
    assert repository.requests[0].purpose is AiPurpose.TRIAGE


def test_a_malformed_answer_is_repaired_once() -> None:
    repository = TriageRepository(pending=(SIGNAL,))
    model = ScriptedModel([response(MALFORMED), response(GOOD_TRIAGE)])

    result = run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert result.triaged == 1
    assert result.repaired == 1
    assert result.requests == 2
    assert "Error:" in model.requests[1].user


def test_two_bad_answers_fail_loudly_and_keep_the_signal() -> None:
    repository = TriageRepository(pending=(SIGNAL,))
    model = ScriptedModel([response(MALFORMED), response(MALFORMED)])

    result = run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert result.failed == 1
    assert repository.statuses[SIGNAL.id] is TriageStatus.FAILED
    assert repository.deleted == []
    assert [record.outcome for record in repository.requests] == [
        AiOutcome.REJECTED,
        AiOutcome.REJECTED,
    ]


def test_it_never_repairs_more_than_once() -> None:
    repository = TriageRepository(pending=(SIGNAL,))
    model = ScriptedModel([response(MALFORMED)] * 5)

    result = run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert result.requests == 2


def test_an_irrelevant_verdict_filters_the_signal() -> None:
    repository = TriageRepository(pending=(SIGNAL,))
    model = ScriptedModel([response(IRRELEVANT_TRIAGE)])

    run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert repository.statuses[SIGNAL.id] is TriageStatus.DONE
    assert repository.filtered == [SIGNAL.id]


def test_a_known_disease_resolves_to_the_vocabulary() -> None:
    repository = TriageRepository(
        pending=(SIGNAL,),
        diseases={"dengue": DENGUE_ID},
    )
    model = ScriptedModel([response(GOOD_TRIAGE)])

    run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert repository.stored[SIGNAL.id].disease_id == DENGUE_ID


def test_an_unknown_disease_is_kept_as_text_and_resolves_to_nothing() -> None:
    repository = TriageRepository(pending=(SIGNAL,), diseases={})
    model = ScriptedModel([response(GOOD_TRIAGE)])

    run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert repository.stored[SIGNAL.id].disease == "dengue"
    assert repository.stored[SIGNAL.id].disease_id is None


def test_the_budget_guard_stops_the_pass_cleanly() -> None:
    repository = TriageRepository(pending=(SIGNAL, SECOND))
    model = ScriptedModel([response(GOOD_TRIAGE)])

    result = run_triage(
        repository,
        model,
        guards=Guards(max_requests=1, max_cost_usd=Decimal("1")),
        now=lambda: NOW,
    )

    assert result.stopped_early is True
    assert result == TriageResult(
        examined=2,
        triaged=1,
        repaired=0,
        filtered=0,
        failed=0,
        unavailable=0,
        requests=1,
        stopped_early=True,
    )
