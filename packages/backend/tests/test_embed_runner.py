import pytest
from episignal_backend.ai.embed import EmbeddingResult
from episignal_backend.embed_runner import Arguments, main, parse_arguments


def test_the_batch_size_defaults_to_configuration() -> None:
    assert parse_arguments([]) == Arguments(batch_size=None)


def test_the_pnpm_double_dash_separator_is_ignored() -> None:
    assert parse_arguments(["--", "--batch-size", "5"]).batch_size == 5


def test_a_successful_run_prints_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "episignal_backend.embed_runner._run",
        lambda arguments: EmbeddingResult(examined=4, embedded=3, failed=1),
    )

    assert main([]) == 0
    assert "examined=4 embedded=3 failed=1" in capsys.readouterr().out


def test_a_failing_run_never_prints_signal_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(arguments: Arguments) -> EmbeddingResult:
        raise RuntimeError("private article body")

    monkeypatch.setattr("episignal_backend.embed_runner._run", explode)

    assert main([]) == 1
    captured = capsys.readouterr()
    assert "private article body" not in captured.err
    assert "Embedding failed" in captured.err
