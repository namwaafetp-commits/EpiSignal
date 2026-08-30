import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from episignal_backend.ai.documents import ChatResponse, ModelSpec, TokenUsage
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.db.types import AiProvider
from episignal_backend.model_check import (
    FIXTURE_ROOT,
    load_cases,
    run_model_check,
    save_result,
    score_extraction,
    score_triage,
)


def _spec(model_id: str = "test/model") -> ModelSpec:
    return ModelSpec(
        id=uuid4(),
        tier=1,
        model_id=model_id,
        label=model_id,
        provider=AiProvider.OPENROUTER,
        prompt_price_per_million=Decimal("1"),
        completion_price_per_million=Decimal("2"),
    )


def test_lite_fixtures_have_twenty_stable_cases_per_purpose() -> None:
    triage = load_cases("triage")
    extraction = load_cases("extraction")

    assert len(triage) == 20
    assert len(extraction) == 20
    assert triage[0].case_id == "TRIAGE-001"
    assert extraction[-1].case_id == "EXTRACT-020"


def test_triage_scoring_exposes_recall_and_false_negatives() -> None:
    score = score_triage(
        {"relevant": True, "disease": "cholera", "country": "AO", "admin1": "Luanda"},
        {
            "relevant": False,
            "public_health": False,
            "category": "not_public_health",
            "event_type": "unknown",
            "confidence": 0.8,
        },
    )

    assert score["fn"] == 1
    assert score["schema_valid"] is True


def test_triage_schema_failure_is_not_a_false_negative() -> None:
    score = score_triage({"relevant": True}, {"relevant": "not-a-bool"})

    assert score["schema_valid"] is False
    assert score["fn"] == 0


def test_extraction_counts_expected_null_as_correct_and_invention_as_failure() -> None:
    case = load_cases("extraction")[1]
    actual = dict(case.expected)
    actual["epidemiology"] = {
        "deaths": {"value": 3, "source_span": "3 deaths", "source_index": 0},
        "total_cases": {"value": 99, "source_span": "3 deaths", "source_index": 0},
    }

    score = score_extraction(case.expected, actual, case.input["raw_text"])

    assert score["schema_valid"] is True
    assert score["unsupported_numeric_claims"] == 1
    assert score["null_correct"] < score["null_slots"]


def test_extraction_grounding_failure_is_visible() -> None:
    case = load_cases("extraction")[0]
    actual = json.loads(json.dumps(case.expected))
    actual["epidemiology"]["confirmed_cases"]["source_span"] = "999 cases"

    score = score_extraction(case.expected, actual, case.input["raw_text"])

    assert score["schema_valid"] is True
    assert score["grounded"] is False
    assert score["grounding_failures"] == 1


class FakeModel:
    def __init__(self, content: str, *, unavailable: bool = False) -> None:
        self.content = content
        self.unavailable = unavailable
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if self.unavailable:
            raise ModelUnavailable("test unavailable")
        return ChatResponse(
            content=self.content,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
            latency_ms=7,
        )


def test_runner_uses_identical_inputs_and_stops_at_request_cap() -> None:
    cases = load_cases("triage")[:2]
    answer = {
        "relevant": True,
        "public_health": True,
        "category": "infectious_disease",
        "event_type": "outbreak_report",
        "disease": "cholera",
        "country": "AO",
        "admin1": "Luanda",
        "confidence": 0.9,
    }
    first = FakeModel(json.dumps(answer))
    second = FakeModel(json.dumps(answer))
    result = run_model_check(
        purpose="triage",
        models=((_spec("a/model"), first), (_spec("b/model"), second)),
        cases=cases,
        max_requests=3,
        max_cost_usd=Decimal("1"),
        clock=lambda: datetime(2026, 8, 30, tzinfo=UTC),
    )

    assert result["status"] == "partial"
    assert result["requests"] == 3
    assert len(first.requests) == 2
    assert len(second.requests) == 1
    assert first.requests[0].user == second.requests[0].user


def test_runner_stops_at_cost_cap_and_keeps_prior_result() -> None:
    case = load_cases("triage")[0]
    answer = json.dumps(
        {
            "relevant": True,
            "public_health": True,
            "category": "infectious_disease",
            "event_type": "outbreak_report",
            "confidence": 0.9,
        }
    )
    result = run_model_check(
        purpose="triage",
        models=((_spec(), FakeModel(answer)),),
        cases=(case, case),
        max_cost_usd=Decimal("0.00001"),
    )

    assert result["status"] == "partial"
    assert len(result["results"]["test/model"]["cases"]) == 1


def test_unavailable_model_is_distinct_from_rejected_answer() -> None:
    case = load_cases("triage")[0]
    result = run_model_check(
        purpose="triage",
        models=((_spec(), FakeModel("{}", unavailable=True)),),
        cases=(case,),
    )

    row = result["results"]["test/model"]["cases"][0]
    assert row["status"] == "unavailable"
    assert row["error"] == "test unavailable"


def test_result_is_saved_as_reproducible_json(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    result = {"git_sha": "abc", "purpose": "triage", "metrics": {"recall": 1.0}}
    save_result(result, path)

    assert json.loads(path.read_text(encoding="utf-8")) == result
    assert FIXTURE_ROOT.is_dir()
