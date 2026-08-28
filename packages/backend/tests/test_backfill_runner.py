import pytest
from episignal_backend.ai.extract import ExtractionResult
from episignal_backend.backfill_runner import Arguments, main, parse_arguments


def _extraction_result(
    *,
    extracted: int = 5,
    reviewed: int = 0,
    unavailable: int = 0,
    storage_failed: int = 0,
) -> ExtractionResult:
    return ExtractionResult(
        examined=5,
        extracted=extracted,
        reviewed=reviewed,
        unavailable=unavailable,
        storage_failed=storage_failed,
        requests=5,
    )


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
    assert "re_extracted=5" in output
    assert "rejected=0" in output
    assert "storage_failed=0" in output


@pytest.mark.parametrize(
    "result",
    [
        _extraction_result(extracted=4, reviewed=1),
        _extraction_result(extracted=4, unavailable=1),
        _extraction_result(extracted=4, storage_failed=1),
    ],
)
def test_any_failed_signal_makes_the_command_fail(
    result: ExtractionResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "episignal_backend.backfill_runner._run",
        lambda arguments: result,
    )

    assert main([]) == 1



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
