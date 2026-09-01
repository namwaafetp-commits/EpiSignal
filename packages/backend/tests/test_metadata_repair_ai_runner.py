from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import episignal_backend.metadata_repair_ai_runner as repair_runner
import pytest
from episignal_backend.ai.extract import ExtractionSignalResult
from episignal_backend.ai.ladder import ClimbOutcome
from episignal_backend.db.session import enforce_read_only_transaction
from episignal_backend.metadata import MetadataEvidence, MetadataFields, ResolvedMetadata
from episignal_backend.metadata_repair_ai_runner import (
    RepairDiagnostic,
    RepairResult,
    _print_diagnostic,
    parse_arguments,
    run_repair_ai,
    unresolved_reason,
)


class ScalarResult:
    def __init__(self, value: str) -> None:
        self.value = value

    def scalar_one(self) -> str:
        return self.value


class QueryResult:
    def __init__(self, *, events=None, rows=None) -> None:
        self.events = events
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.events if self.events is not None else self.rows


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


def test_unresolved_reason_reports_disease_vocabulary_miss() -> None:
    reason = unresolved_reason(
        event=SimpleNamespace(disease_id=None, country_code="US", admin1=None),
        evidence=(
            MetadataEvidence(
                title="Meningococcal outbreak",
                text="body",
                extraction=MetadataFields(disease="Meningococcal disease", country="US"),
            ),
        ),
        resolved=ResolvedMetadata(disease_text="meningococcal disease", country_code="US"),
    )

    assert reason == "disease_vocabulary_miss"


def test_unresolved_reason_reports_country_validation_failure() -> None:
    reason = unresolved_reason(
        event=SimpleNamespace(disease_id=uuid4(), country_code=None, admin1=None),
        evidence=(
            MetadataEvidence(
                title="Outbreak",
                text="body",
                extraction=MetadataFields(disease="measles", country="ZZ"),
            ),
        ),
        resolved=ResolvedMetadata(disease_id=uuid4()),
    )

    assert reason == "country_validation_failed"


def test_unresolved_reason_reports_admin1_validation_failure_without_country_loss() -> None:
    reason = unresolved_reason(
        event=SimpleNamespace(disease_id=uuid4(), country_code="US", admin1=None),
        evidence=(
            MetadataEvidence(
                title="Outbreak",
                text="body",
                extraction=MetadataFields(
                    disease="measles", country="US", admin1="Unknown Province"
                ),
            ),
        ),
        resolved=ResolvedMetadata(disease_id=uuid4(), country_code="US"),
    )

    assert reason == "admin1_validation_failed"


def test_unresolved_reason_reports_extraction_rejection_and_request_guard() -> None:
    event = SimpleNamespace(disease_id=None, country_code=None, admin1=None)
    evidence = (MetadataEvidence(title="Outbreak", text="body"),)
    resolved = ResolvedMetadata()

    assert (
        unresolved_reason(
            event=event,
            evidence=evidence,
            resolved=resolved,
            extraction_outcomes=("rejected",),
        )
        == "extraction_rejected"
    )
    assert (
        unresolved_reason(
            event=event,
            evidence=evidence,
            resolved=resolved,
            request_guard=True,
        )
        == "request_guard"
    )


def test_diagnostic_print_is_concise_and_excludes_article_body(capsys) -> None:
    _print_diagnostic(
        RepairDiagnostic(
            event_id="event-1",
            headline="Meningococcal outbreak",
            extraction_reused=False,
            extraction_reextracted=True,
            extraction_outcome="accepted",
            model_id="model-1",
            confidence=0.9,
            initial=True,
            expanded=False,
            raw_disease="Meningococcal disease",
            raw_country="US",
            raw_admin1="Pennsylvania",
            validated_disease_id=None,
            validated_disease_text="meningococcal disease",
            validated_country_code="US",
            validated_admin1=None,
            result="unresolved",
            unresolved_reason="disease_vocabulary_miss",
        )
    )

    output = capsys.readouterr().out
    assert "DIAGNOSTIC event_id=event-1" in output
    assert "reason=disease_vocabulary_miss" in output
    assert "Meningococcal outbreak" not in output


def test_dry_run_request_guard_returns_diagnostic_without_writes(monkeypatch) -> None:
    event_id = uuid4()
    signal = SimpleNamespace(
        id=uuid4(),
        title="Outbreak report",
        raw_text="article body",
        public_health_relevant=True,
        ai_extraction=None,
        ai_model=None,
    )
    event = SimpleNamespace(
        id=event_id,
        country_code=None,
        admin1=None,
        disease_id=None,
        event_type=None,
        headline="Outbreak report",
    )

    class Session:
        def __init__(self) -> None:
            self.calls = 0
            self.committed = False

        def execute(self, statement):
            self.calls += 1
            return (
                QueryResult(events=[event])
                if self.calls == 1
                else QueryResult(rows=[(signal, "source")])
            )

        def commit(self) -> None:
            self.committed = True

    repository = Mock()
    monkeypatch.setattr(repair_runner, "build_extraction_ladder", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        repair_runner,
        "extract_signal",
        lambda *args, **kwargs: ExtractionSignalResult(
            outcome=ClimbOutcome.GUARD,
            extraction=None,
            error="request guard",
            attempts=(),
        ),
    )

    session = Session()
    result = run_repair_ai(
        session,
        repository,
        Mock(),
        Mock(),
        apply=False,
        limit=1,
        max_ai_requests=1,
        max_cost_usd=Decimal("1"),
        max_tier=3,
    )

    assert result.diagnostics[0].unresolved_reason == "request_guard"
    assert session.calls == 2
    assert session.committed is False
    repository.record_request.assert_not_called()
    repository.record_extraction.assert_not_called()
