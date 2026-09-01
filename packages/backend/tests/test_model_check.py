import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from episignal_backend.ai.documents import (
    ChatResponse,
    ExtractableSignal,
    ModelSpec,
    TokenUsage,
    TriageableSignal,
)
from episignal_backend.ai.extract import DEFAULT_MAX_INPUT_CHARACTERS, EXTRACTION_SCHEMA_NAME
from episignal_backend.ai.prompts import extraction_prompt, triage_prompt
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.ai.schema import extraction_json_schema, triage_json_schema
from episignal_backend.ai.triage import TRIAGE_CONTENT_CHARACTERS
from episignal_backend.db.types import AiProvider
from episignal_backend.model_check import (
    FIXTURE_ROOT,
    FIXTURE_SOURCE_NAME,
    FIXTURE_URL_BASE,
    _fixture_id,
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


def test_ambiguous_triage_gold_does_not_infer_disease_or_geography() -> None:
    cases = {case.case_id: case for case in load_cases("triage")}

    assert cases["TRIAGE-001"].expected["admin1"] is None
    assert cases["TRIAGE-003"].expected["admin1"] is None
    assert cases["TRIAGE-004"].expected["admin1"] is None
    assert cases["TRIAGE-006"].expected["disease"] is None
    assert cases["TRIAGE-006"].expected["country"] is None
    assert cases["TRIAGE-006"].expected["admin1"] is None
    assert cases["TRIAGE-011"].expected["country"] is None
    assert cases["TRIAGE-011"].expected["admin1"] is None
    assert cases["TRIAGE-012"].expected["admin1"] is None
    assert cases["TRIAGE-008"].expected["admin1"] == "Kano"
    assert cases["TRIAGE-018"].expected["admin1"] == "Cebu"


def test_model_check_uses_production_prompt_seams_and_request_contract() -> None:
    triage_case = load_cases("triage")[0]
    triage_model = FakeModel(
        json.dumps(
            {
                "relevant": True,
                "public_health": True,
                "category": "infectious_disease",
                "event_type": "outbreak_report",
                "confidence": 0.9,
            }
        )
    )
    run_model_check(
        purpose="triage",
        models=((_spec(), triage_model),),
        cases=(triage_case,),
    )
    triage_signal = TriageableSignal(
        id=_fixture_id(triage_case.case_id),
        title=triage_case.input["title"],
        article_content=triage_case.input["excerpt"],
        source_name=FIXTURE_SOURCE_NAME,
        url=f"{FIXTURE_URL_BASE}{triage_case.case_id}",
        language="en",
    )
    triage_request = triage_model.requests[0]
    expected_system, expected_user = triage_prompt(
        triage_signal, max_characters=TRIAGE_CONTENT_CHARACTERS
    )
    assert (triage_request.system, triage_request.user) == (expected_system, expected_user)
    assert triage_request.response_schema == triage_json_schema()
    assert triage_request.schema_name == "triage_verdict"
    assert triage_request.temperature == 0.0

    extraction_case = load_cases("extraction")[0]
    extraction_model = FakeModel(json.dumps(extraction_case.expected))
    run_model_check(
        purpose="extraction",
        models=((_spec(), extraction_model),),
        cases=(extraction_case,),
    )
    extraction_signal = ExtractableSignal(
        id=_fixture_id(extraction_case.case_id),
        title=extraction_case.input["title"],
        raw_text=extraction_case.input["raw_text"],
    )
    extraction_request = extraction_model.requests[0]
    expected_system, expected_user = extraction_prompt(
        extraction_signal, max_characters=DEFAULT_MAX_INPUT_CHARACTERS
    )
    assert (extraction_request.system, extraction_request.user) == (expected_system, expected_user)
    assert extraction_request.response_schema == extraction_json_schema()
    assert extraction_request.schema_name == EXTRACTION_SCHEMA_NAME
    assert extraction_request.temperature == 0.0


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
