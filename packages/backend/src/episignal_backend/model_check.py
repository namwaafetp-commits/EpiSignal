"""Small, offline-first model comparison tool for the Lean MVP.

This module intentionally has no database dependency. It sends the same
committed fixtures through an explicitly selected model boundary, reuses the
existing Pydantic contracts and grounding checks, and writes a JSON evidence
file. It does not participate in production routing.
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from episignal_backend.ai.documents import ChatRequest, ChatResponse, ModelSpec
from episignal_backend.ai.ladder import cost_usd
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.ai.schema import Extraction, TriageVerdict
from episignal_backend.ai.validate import check_grounding

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "model_check"
DEFAULT_MAX_REQUESTS = 50
DEFAULT_MAX_COST_USD = Decimal("0.25")


def rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


class ModelBoundary(Protocol):
    def complete(self, request: ChatRequest) -> ChatResponse: ...


class CheckCase:
    def __init__(self, case_id: str, input: dict[str, Any], expected: dict[str, Any]) -> None:
        self.case_id = case_id
        self.input = input
        self.expected = expected


def load_cases(purpose: str, root: Path = FIXTURE_ROOT) -> tuple[CheckCase, ...]:
    if purpose not in {"triage", "extraction"}:
        raise ValueError("F Lite supports only triage and extraction")
    raw = json.loads((root / f"{purpose}.json").read_text(encoding="utf-8"))
    cases = tuple(CheckCase(item["case_id"], item["input"], item["expected"]) for item in raw)
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate case_id in {purpose} fixture")
    return cases


def _request(purpose: str, model_id: str, payload: dict[str, Any]) -> ChatRequest:
    if purpose == "triage":
        schema = TriageVerdict.model_json_schema()
    else:
        schema = Extraction.model_json_schema()
    return ChatRequest(
        model_id=model_id,
        system=(
            "Return only JSON matching the supplied schema. Do not invent values. "
            f"This is an offline {purpose} model check."
        ),
        user=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        response_schema=schema,
        schema_name=f"model_check_{purpose}",
        temperature=0.0,
    )


def score_triage(expected: dict[str, Any], actual: dict[str, Any] | None) -> dict[str, Any]:
    try:
        verdict = TriageVerdict.model_validate(actual or {})
    except ValidationError:
        return {"schema_valid": False, "schema_failures": 1, "tp": 0, "fp": 0, "tn": 0, "fn": 0}
    expected_relevant = bool(expected["relevant"])
    actual_relevant = verdict.relevant
    tp = int(expected_relevant and actual_relevant)
    fp = int(not expected_relevant and actual_relevant)
    tn = int(not expected_relevant and not actual_relevant)
    fn = int(expected_relevant and not actual_relevant)
    return {
        "schema_valid": True,
        "schema_failures": 0,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "relevant_correct": int(expected_relevant == actual_relevant),
        "disease_correct": int(expected.get("disease") == verdict.disease),
        "location_correct": int(
            expected.get("country") == verdict.country and expected.get("admin1") == verdict.admin1
        ),
    }


def score_extraction(
    expected: dict[str, Any], actual: dict[str, Any] | None, raw_text: str
) -> dict[str, Any]:
    try:
        expected_model = Extraction.model_validate(expected)
        actual_model = Extraction.model_validate(actual or {})
    except ValidationError:
        return {"schema_valid": False, "schema_failures": 1, "grounded": False}
    try:
        check_grounding(actual_model, (raw_text,))
        grounded = True
    except Exception:
        grounded = False
    expected_counts = expected_model.epidemiology.model_dump(mode="json")
    actual_counts = actual_model.epidemiology.model_dump(mode="json")
    count_names = tuple(expected_counts)
    populated = tuple(name for name in count_names if expected_counts[name] is not None)
    numeric_correct = sum(expected_counts[name] == actual_counts.get(name) for name in populated)
    unsupported = sum(
        expected_counts[name] is None and actual_counts.get(name) is not None
        for name in count_names
    )
    null_correct = sum(
        (expected_counts[name] is None) == (actual_counts.get(name) is None) for name in count_names
    )
    return {
        "schema_valid": True,
        "schema_failures": 0,
        "grounded": grounded,
        "numeric_correct": numeric_correct,
        "numeric_expected": len(populated),
        "unsupported_numeric_claims": unsupported,
        "null_correct": null_correct,
        "null_slots": len(count_names),
        "brief_correct": int(
            expected_model.brief == actual_model.brief and len(actual_model.brief) == 5
        ),
        "grounding_failures": int(not grounded),
    }


def aggregate(purpose: str, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    attempted = len(rows)
    successful = [row for row in rows if row.get("status") == "accepted"]
    metrics: dict[str, Any] = {
        "cases": attempted,
        "accepted": len(successful),
        "schema_failures": sum(row.get("score", {}).get("schema_failures", 0) for row in rows),
        "total_cost_usd": str(sum((Decimal(row["cost_usd"]) for row in rows), Decimal("0"))),
        "average_latency_ms": rate(sum(row["latency_ms"] for row in rows), attempted),
    }
    if purpose == "triage":
        tp = sum(row.get("score", {}).get("tp", 0) for row in rows)
        fp = sum(row.get("score", {}).get("fp", 0) for row in rows)
        tn = sum(row.get("score", {}).get("tn", 0) for row in rows)
        fn = sum(row.get("score", {}).get("fn", 0) for row in rows)
        metrics.update(
            {
                "accuracy": rate(tp + tn, attempted),
                "recall": rate(tp, tp + fn),
                "false_negatives": fn,
                "false_positives": fp,
                "disease_accuracy": rate(
                    sum(row.get("score", {}).get("disease_correct", 0) for row in rows), attempted
                ),
                "location_accuracy": rate(
                    sum(row.get("score", {}).get("location_correct", 0) for row in rows), attempted
                ),
            }
        )
    else:
        metrics.update(
            {
                "schema_valid_rate": rate(
                    sum(row.get("score", {}).get("schema_valid", False) for row in rows), attempted
                ),
                "grounding_pass_rate": rate(
                    sum(row.get("score", {}).get("grounded", False) for row in rows), attempted
                ),
                "numeric_accuracy": rate(
                    sum(row.get("score", {}).get("numeric_correct", 0) for row in rows),
                    sum(row.get("score", {}).get("numeric_expected", 0) for row in rows),
                ),
                "unsupported_numeric_claims": sum(
                    row.get("score", {}).get("unsupported_numeric_claims", 0) for row in rows
                ),
                "null_correctness": rate(
                    sum(row.get("score", {}).get("null_correct", 0) for row in rows),
                    sum(row.get("score", {}).get("null_slots", 0) for row in rows),
                ),
            }
        )
    return metrics


def run_model_check(
    *,
    purpose: str,
    models: Sequence[tuple[ModelSpec, ModelBoundary]],
    cases: Sequence[CheckCase] | None = None,
    max_cases: int | None = None,
    max_requests: int = DEFAULT_MAX_REQUESTS,
    max_cost_usd: Decimal = DEFAULT_MAX_COST_USD,
    git_sha: str = "offline-test",
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    selected_cases = tuple((cases or load_cases(purpose))[:max_cases])
    rows_by_model: dict[str, list[dict[str, Any]]] = {}
    requests = 0
    spent = Decimal("0")
    status = "completed"
    started = clock()
    for spec, model in sorted(models, key=lambda pair: pair[0].model_id):
        rows: list[dict[str, Any]] = []
        rows_by_model[spec.model_id] = rows
        for case in selected_cases:
            if requests >= max_requests or spent >= max_cost_usd:
                status = "partial"
                break
            request = _request(purpose, spec.model_id, case.input)
            requests += 1
            try:
                response = model.complete(request)
            except ModelUnavailable as error:
                rows.append(
                    {
                        "case_id": case.case_id,
                        "status": "unavailable",
                        "cost_usd": "0.000000",
                        "latency_ms": 0,
                        "score": {},
                        "error": str(error),
                    }
                )
                continue
            cost = cost_usd(response.usage, spec)
            spent += cost
            actual: dict[str, Any] | None = None
            error_text: str | None = None
            try:
                actual = json.loads(response.content)
                if not isinstance(actual, dict):
                    raise ValueError("model output must be a JSON object")
            except (ValueError, json.JSONDecodeError) as error:
                error_text = str(error)
            score = (
                score_triage(case.expected, actual)
                if purpose == "triage"
                else score_extraction(case.expected, actual, case.input["raw_text"])
            )
            rows.append(
                {
                    "case_id": case.case_id,
                    "status": "accepted" if score.get("schema_valid") else "rejected",
                    "cost_usd": str(cost),
                    "latency_ms": response.latency_ms,
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "score": score,
                    "expected": case.expected,
                    "actual": actual,
                    "error": error_text,
                }
            )
            if spent >= max_cost_usd:
                status = "partial"
                break
        if status == "partial":
            break
    return {
        "git_sha": git_sha,
        "date": started.isoformat(),
        "fixture_version": "model-check-v1",
        "purpose": purpose,
        "models": [spec.model_id for spec, _ in sorted(models, key=lambda pair: pair[0].model_id)],
        "status": status,
        "guard": {"max_requests": max_requests, "max_cost_usd": str(max_cost_usd)},
        "requests": requests,
        "total_cost_usd": str(spent),
        "results": {
            model_id: {"metrics": aggregate(purpose, rows), "cases": rows}
            for model_id, rows in rows_by_model.items()
        },
    }


def save_result(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare explicitly selected models on F Lite fixtures"
    )
    parser.add_argument("--purpose", choices=("triage", "extraction"), default="triage")
    parser.add_argument("--model", default=None, help="one explicit model ID")
    parser.add_argument("--models", default=None, help="comma-separated explicit model IDs")
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
    parser.add_argument("--max-cost-usd", type=Decimal, default=DEFAULT_MAX_COST_USD)
    parser.add_argument("--output", type=Path, default=None)
    raw_args = list(argv) if argv is not None else sys.argv[1:]
    if raw_args and raw_args[0] == "--":
        raw_args = raw_args[1:]
    args = parser.parse_args(raw_args)
    from episignal_backend.ai.routing import RoutedChatModel, build_adapters
    from episignal_backend.config import get_settings
    from episignal_backend.seeds import load_ai_models

    settings = get_settings()
    requested = args.models or args.model
    if not requested:
        parser.error("one of --model or --models is required")
    seed_by_id = {seed.model_id: seed for seed in load_ai_models()}
    requested_ids = tuple(
        sorted({model_id.strip() for model_id in requested.split(",") if model_id.strip()})
    )
    missing = [model_id for model_id in requested_ids if model_id not in seed_by_id]
    if missing:
        parser.error(
            "models are not present in database/seeds/ai_models.json: " + ", ".join(missing)
        )
    specs = tuple(
        ModelSpec(
            id=__import__("uuid").uuid4(),
            tier=seed_by_id[model_id].tier,
            model_id=model_id,
            label=seed_by_id[model_id].label,
            provider=seed_by_id[model_id].provider,
            prompt_price_per_million=seed_by_id[model_id].prompt_price_per_million,
            completion_price_per_million=seed_by_id[model_id].completion_price_per_million,
        )
        for model_id in requested_ids
    )
    try:
        adapters = build_adapters(
            openrouter_api_key=(
                settings.openrouter_api_key.get_secret_value()
                if settings.openrouter_api_key
                else None
            ),
            gemini_api_key=(
                settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
            ),
            openrouter_base_url=settings.openrouter_base_url,
            gemini_base_url=settings.gemini_base_url,
            timeout_seconds=settings.ai_request_timeout_seconds,
            max_attempts=settings.ai_max_attempts_per_tier,
        )
    except Exception as error:
        parser.error(f"no provider API key is configured: {error}")
    routed = RoutedChatModel.from_specs(list(specs), adapters)
    result = run_model_check(
        purpose=args.purpose,
        models=tuple((spec, routed) for spec in specs),
        max_cases=args.max_cases,
        max_requests=args.max_requests,
        max_cost_usd=args.max_cost_usd,
        git_sha=_git_sha(),
    )
    output = (
        args.output or Path("benchmarks/results") / f"{datetime.now(UTC).date()}-model-check.json"
    )
    save_result(result, output)
    print(
        json.dumps({"status": result["status"], "output": str(output), "models": result["models"]})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
