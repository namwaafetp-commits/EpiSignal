from decimal import Decimal

import episignal_backend.metadata_repair_ai_runner as repair_runner
from episignal_backend.metadata_repair_ai_runner import RepairResult, parse_arguments


def test_ai_repair_defaults_to_a_dry_run_with_no_unbounded_request_budget() -> None:
    arguments = parse_arguments([])

    assert arguments.apply is False
    assert arguments.limit is None
    assert arguments.max_ai_requests is None


def test_ai_repair_requires_explicit_apply_and_supports_both_limits() -> None:
    arguments = parse_arguments(["--apply", "--limit", "20", "--max-ai-requests", "3"])

    assert arguments.apply is True
    assert arguments.limit == 20
    assert arguments.max_ai_requests == 3


def test_ai_repair_result_reports_cost_without_requiring_a_write() -> None:
    result = RepairResult(ai_requests=2, ai_cost_usd=Decimal("0.012345"))

    assert result.ai_requests == 2
    assert result.ai_cost_usd == Decimal("0.012345")


def test_ai_repair_cli_prints_in_memory_cost(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        repair_runner,
        "_run",
        lambda arguments: RepairResult(ai_requests=2, ai_cost_usd=Decimal("0.012345")),
    )

    assert repair_runner.main(["--dry-run"]) == 0
    assert "ai_requests=2 ai_cost_usd=0.012345" in capsys.readouterr().out
