"""Tests for Gemini identity extraction and its bounded repair."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatRequest,
    ChatResponse,
    ExtractableSignal,
    ModelSpec,
    StoredExtraction,
)
from episignal_backend.ai.extract import ExtractionResult, extract_signal, run_extraction
from episignal_backend.ai.ladder import Guards, RunBudget
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.ai.schema import Extraction, ExtractionLocation
from episignal_backend.db.types import AiOutcome, AiProvider, AiPurpose

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
FIRST = UUID("b3f1c2d4-0000-4000-8000-000000000001")


def spec() -> ModelSpec:
    return ModelSpec(
        id=uuid4(),
        tier=1,
        model_id="google/gemini-3.1-flash-lite",
        label="Gemini 3.1 Flash-Lite",
        provider=AiProvider.GEMINI,
        purpose=AiPurpose.EXTRACTION,
        prompt_price_per_million=Decimal("0"),
        completion_price_per_million=Decimal("0"),
    )


class ScriptedModel:
    def __init__(self, answers: list[object]) -> None:
        self.answers = list(answers)
        self.requests: list[ChatRequest] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return ChatResponse(content=str(answer), latency_ms=1)


class Repository:
    def __init__(self, pending: Sequence[ExtractableSignal]) -> None:
        self.pending = tuple(pending)
        self.stored: dict[UUID, StoredExtraction] = {}
        self.requests: list[AiRequestRecord] = []

    def models(self) -> Sequence[ModelSpec]:
        return (spec(),)

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        return self.pending[:limit]

    def record_request(self, record: AiRequestRecord) -> None:
        self.requests.append(record)

    def record_extraction(self, signal_id: UUID, stored: StoredExtraction) -> None:
        self.stored[signal_id] = stored

    def record_extraction_failure(self, signal_id: UUID) -> None:
        pass

    def resolve_disease(self, name: str) -> UUID | None:
        return None

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def signal() -> ExtractableSignal:
    return ExtractableSignal(
        id=FIRST, title="Measles in Cebu", raw_text="Measles was reported in Cebu."
    )


def response(payload: dict[str, object]) -> str:
    return json.dumps(payload)


def budget() -> RunBudget:
    return RunBudget(Guards(max_requests=5, max_cost_usd=Decimal("1")))


def test_complete_identity_is_stored_with_gemini_model() -> None:
    repository = Repository((signal(),))
    model = ScriptedModel(
        [
            response(
                {"disease": "measles", "locations": [{"town": "Cebu", "country": "Philippines"}]}
            )
        ]
    )

    result = run_extraction(
        repository, model, guards=Guards(max_requests=5, max_cost_usd=Decimal("1")), now=lambda: NOW
    )

    assert result == ExtractionResult(examined=1, extracted=1, requests=1)
    assert repository.stored[FIRST].model_id == "google/gemini-3.1-flash-lite"
    assert repository.stored[FIRST].extraction == Extraction(
        disease="measles", locations=(ExtractionLocation(town="Cebu", country="Philippines"),)
    )


def test_identity_prompt_resolves_containing_country_and_ignores_publisher_geography() -> None:
    model = ScriptedModel(
        [response({"disease": "dengue", "locations": [{"town": "Cebu", "country": "Philippines"}]})]
    )
    result = extract_signal(
        ExtractableSignal(
            id=FIRST,
            title="Dengue reported in Cebu",
            raw_text="WHO Manila said cases were found in Cebu.",
        ),
        model,
        spec=spec(),
        budget=budget(),
    )
    assert result.extraction == Extraction(
        disease="dengue", locations=(ExtractionLocation(town="Cebu", country="Philippines"),)
    )
    assert "containing country" in model.requests[0].system
    assert "publisher location" in model.requests[0].system
    assert "organization headquarters" in model.requests[0].system


def test_identity_supports_country_only_multiple_locations_unknown_and_null() -> None:
    model = ScriptedModel(
        [
            response(
                {
                    "disease": "novel fever",
                    "locations": [
                        {"town": None, "country": "Thailand"},
                        {"town": "Cebu", "country": "Philippines"},
                    ],
                }
            )
        ]
    )
    result = extract_signal(signal(), model, spec=spec(), budget=budget())
    assert result.extraction is not None
    assert result.extraction.disease == "novel fever"
    assert result.extraction.locations[0].town is None

    null_result = extract_signal(
        signal(),
        ScriptedModel(
            [
                response({"disease": None, "locations": []}),
                response({"disease": None, "locations": []}),
            ]
        ),
        spec=spec(),
        budget=budget(),
    )
    assert null_result.extraction == Extraction(disease=None, locations=())


def test_incomplete_identity_gets_one_same_model_repair() -> None:
    model = ScriptedModel(
        [
            response({"disease": "measles", "locations": [{"town": "Cebu", "country": None}]}),
            response(
                {"disease": "measles", "locations": [{"town": "Cebu", "country": "Philippines"}]}
            ),
        ]
    )

    result = extract_signal(signal(), model, spec=spec(), budget=budget())

    assert result.extraction is not None and result.extraction.locations[0].country == "Philippines"
    assert len(model.requests) == 2
    assert (
        model.requests[0].model_id == model.requests[1].model_id == "google/gemini-3.1-flash-lite"
    )


def test_retry_is_at_most_once_and_best_valid_partial_survives_failure() -> None:
    model = ScriptedModel(
        [
            response({"disease": "measles", "locations": [{"town": "Cebu", "country": None}]}),
            ModelUnavailable("timeout"),
        ]
    )

    result = extract_signal(signal(), model, spec=spec(), budget=budget())

    assert result.extraction is not None
    assert result.extraction.disease == "measles"
    assert len(model.requests) == 2


def test_malformed_initial_response_is_not_retried_as_a_provider_fallback() -> None:
    model = ScriptedModel(["not json"])
    result = extract_signal(signal(), model, spec=spec(), budget=budget())
    assert result.extraction is None
    assert len(model.requests) == 1


def test_unavailable_provider_leaves_signal_unstored() -> None:
    repository = Repository((signal(),))
    model = ScriptedModel([ModelUnavailable("429")])
    result = run_extraction(
        repository, model, guards=Guards(max_requests=5, max_cost_usd=Decimal("1")), now=lambda: NOW
    )
    assert result.unavailable == 1
    assert repository.stored == {}
    assert repository.requests[0].outcome is AiOutcome.UNAVAILABLE
