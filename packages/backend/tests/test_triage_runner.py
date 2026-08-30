import pytest
from episignal_backend.ai.triage import TriageResult
from episignal_backend.triage_runner import Arguments, main, parse_arguments


def test_the_limit_defaults_to_configuration() -> None:
    assert parse_arguments([]) == Arguments(limit=None)


def test_the_pnpm_double_dash_separator_is_ignored() -> None:
    assert parse_arguments(["--", "--limit", "5"]).limit == 5


def test_a_successful_run_prints_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "episignal_backend.triage_runner._run",
        lambda arguments: TriageResult(
            examined=4,
            triaged=3,
            repaired=1,
            filtered=1,
            failed=0,
            unavailable=0,
            requests=5,
        ),
    )

    assert main([]) == 0
    assert (
        "examined=4 triaged=3 repaired=1 filtered=1 failed=0 unavailable=0 requests=5"
        in capsys.readouterr().out
    )


def test_a_failing_run_never_prints_a_body_or_a_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(arguments: Arguments) -> TriageResult:
        raise RuntimeError("sk-secret-value beside a private article body")

    monkeypatch.setattr("episignal_backend.triage_runner._run", explode)

    assert main([]) == 1
    captured = capsys.readouterr()
    assert "sk-secret-value" not in captured.err
    assert "private article body" not in captured.err
    assert "Triage failed" in captured.err
