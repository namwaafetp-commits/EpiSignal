import pytest
from episignal_backend.ai.classify import ClassificationResult
from episignal_backend.ai.extract import ExtractionResult
from episignal_backend.extract_runner import Arguments, main, parse_arguments


def _classification_result() -> ClassificationResult:
    return ClassificationResult(
        examined=10, relevant=5, irrelevant=5, reviewed=0, unavailable=0, requests=1
    )


def _extraction_result() -> ExtractionResult:
    return ExtractionResult(examined=5, extracted=5, reviewed=0, unavailable=0, requests=5)


def test_defaults_run_both_stages() -> None:
    assert parse_arguments([]) == Arguments(limit=None, batch_size=None, stage="both")


def test_a_single_stage_can_be_selected() -> None:
    assert parse_arguments(["--stage", "classify"]).stage == "classify"


def test_an_unknown_stage_is_refused() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["--stage", "guess"])


def test_the_pnpm_double_dash_separator_is_ignored() -> None:
    assert parse_arguments(["--", "--limit", "5"]).limit == 5


def test_a_successful_run_prints_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "episignal_backend.extract_runner._run",
        lambda arguments: (_classification_result(), _extraction_result()),
    )

    assert main([]) == 0

    output = capsys.readouterr().out
    assert "classified=" in output
    assert "extracted=" in output


def test_a_missing_api_key_stops_the_run_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(arguments: Arguments) -> None:
        raise RuntimeError("EPISIGNAL_OPENROUTER_API_KEY is not set")

    monkeypatch.setattr("episignal_backend.extract_runner._run", explode)

    assert main([]) == 1
    assert "OPENROUTER" in capsys.readouterr().err


def test_a_failing_run_never_prints_a_body_or_a_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(arguments: Arguments) -> None:
        raise RuntimeError("sk-secret-value leaked into an exception")

    monkeypatch.setattr("episignal_backend.extract_runner._run", explode)

    assert main([]) == 1
    captured = capsys.readouterr()
    assert "sk-secret-value" not in captured.err
    assert "sk-secret-value" not in captured.out
