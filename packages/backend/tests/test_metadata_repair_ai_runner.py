from decimal import Decimal
from unittest.mock import Mock

import episignal_backend.metadata_repair_ai_runner as repair_runner
import pytest
from episignal_backend.db.session import enforce_read_only_transaction
from episignal_backend.metadata_repair_ai_runner import RepairResult, parse_arguments


class ScalarResult:
    def __init__(self, value: str) -> None:
        self.value = value

    def scalar_one(self) -> str:
        return self.value


def test_ai_repair_defaults_to_a_dry_run_with_no_unbounded_request_budget() -> None:
    arguments = parse_arguments([])

    assert arguments.apply is False
    assert arguments.enforce_read_only is False
    assert arguments.limit is None
    assert arguments.max_ai_requests is None


def test_ai_repair_requires_explicit_apply_and_supports_both_limits() -> None:
    arguments = parse_arguments(
        [
            "--dry-run",
            "--enforce-read-only",
            "--limit",
            "20",
            "--max-ai-requests",
            "3",
        ]
    )

    assert arguments.apply is False
    assert arguments.enforce_read_only is True
    assert arguments.limit == 20
    assert arguments.max_ai_requests == 3


def test_ai_repair_rejects_apply_with_enforced_read_only() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["--apply", "--enforce-read-only"])


def test_read_only_transaction_sets_and_verifies_database_mode() -> None:
    session = Mock()
    session.execute.side_effect = [None, ScalarResult("on")]

    enforce_read_only_transaction(session)

    assert session.execute.call_count == 2
    assert str(session.execute.call_args_list[0].args[0]) == "SET TRANSACTION READ ONLY"
    assert str(session.execute.call_args_list[1].args[0]) == "SHOW transaction_read_only"


def test_read_only_transaction_fails_closed_when_database_reports_off() -> None:
    session = Mock()
    session.execute.side_effect = [None, ScalarResult("off")]

    with pytest.raises(RuntimeError, match="read-only transaction enforcement failed"):
        enforce_read_only_transaction(session)


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
