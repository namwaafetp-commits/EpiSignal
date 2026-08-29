"""Tests for the second-pass AI disease classifier."""

import json
from decimal import Decimal
from uuid import uuid4

from episignal_backend.ai.classify_disease import (
    DiseaseCandidate,
    classify_disease,
    disease_classify_prompt,
)
from episignal_backend.ai.documents import ChatRequest, ChatResponse, ModelSpec, TokenUsage


def _spec() -> ModelSpec:
    return ModelSpec(
        id=uuid4(),
        tier=3,
        model_id="vendor3/model:pro",
        label="Tier 3",
        prompt_price_per_million=Decimal("0"),
        completion_price_per_million=Decimal("0"),
    )


def _candidates() -> list[DiseaseCandidate]:
    return [
        DiseaseCandidate(
            slug="ebola-virus-disease",
            canonical_name="Ebola virus disease",
            synonyms=["EVD", "Ebola haemorrhagic fever"],
        ),
        DiseaseCandidate(
            slug="cholera",
            canonical_name="Cholera",
            synonyms=["Vibrio cholerae infection"],
        ),
    ]


class ScriptedModel:
    def __init__(self, script: list[object]) -> None:
        self.script = script
        self.requests: list[ChatRequest] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        answer = self.script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return ChatResponse(
            content=str(answer),
            usage=TokenUsage(prompt_tokens=200, completion_tokens=20),
            http_status=200,
            latency_ms=150,
        )


def test_classify_disease_returns_slug() -> None:
    model = ScriptedModel([json.dumps({"slug": "ebola-virus-disease"})])
    result = classify_disease(model, _spec(), "Ebola", _candidates())
    assert result == "ebola-virus-disease"


def test_classify_disease_returns_null() -> None:
    model = ScriptedModel([json.dumps({"slug": None})])
    result = classify_disease(model, _spec(), "some unknown pathogen", _candidates())
    assert result is None


def test_classify_disease_unknown_slug_returns_none() -> None:
    """AI returned a slug that is not in the known candidate set -- reject it."""
    model = ScriptedModel([json.dumps({"slug": "not-in-list"})])
    result = classify_disease(model, _spec(), "Ebola", _candidates())
    assert result is None


def test_classify_disease_exception_returns_none() -> None:
    model = ScriptedModel([RuntimeError("provider exploded")])
    result = classify_disease(model, _spec(), "Ebola", _candidates())
    assert result is None


def test_disease_classify_prompt_contains_candidates() -> None:
    candidates = _candidates()
    _system, user = disease_classify_prompt("Ebola", candidates)
    assert "ebola-virus-disease" in user
    assert "Ebola virus disease" in user
    assert "cholera" in user
