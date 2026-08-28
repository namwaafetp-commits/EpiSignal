import pytest
from episignal_backend.ai.extract import ExtractionResult
from episignal_backend.backfill_runner import Arguments, main, parse_arguments


def _extraction_result() -> ExtractionResult:
    return ExtractionResult(examined=5, extracted=5, reviewed=0, unavailable=0, requests=5)


def test_defaults_set_no_overrides() -> None:
    assert parse_arguments([]) == Arguments(limit=None)


def test_the_limit_can_be_passed_from_the_command_line() -> None:
    assert parse_arguments(["--limit", "20"]).limit == 20


def test_the_pnpm_double_dash_separator_is_ignored() -> None:
    assert parse_arguments(["--", "--limit", "5"]).limit == 5


def test_a_successful_run_prints_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "episignal_backend.backfill_runner._run",
        lambda arguments: _extraction_result(),
    )

    assert main([]) == 0

    output = capsys.readouterr().out
    assert "examined=5" in output
    assert "extracted=5" in output


def test_a_missing_api_key_stops_the_run_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(arguments: Arguments) -> None:
        raise RuntimeError("EPISIGNAL_OPENROUTER_API_KEY is not set")

    monkeypatch.setattr("episignal_backend.backfill_runner._run", explode)

    assert main([]) == 1
    assert "OPENROUTER" in capsys.readouterr().err


def test_a_failing_run_never_prints_a_body_or_a_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(arguments: Arguments) -> None:
        raise RuntimeError("sk-secret-value leaked into an exception")

    monkeypatch.setattr("episignal_backend.backfill_runner._run", explode)

    assert main([]) == 1
    captured = capsys.readouterr()
    assert "sk-secret-value" not in captured.err
    assert "sk-secret-value" not in captured.out
