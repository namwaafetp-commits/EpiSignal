import pytest
from episignal_backend.retrieve_runner import main, parse_arguments


def test_parses_explicit_attempts() -> None:
    assert parse_arguments(["--max-attempts", "5"]).max_attempts == 5


def test_parses_explicit_batch_size() -> None:
    assert parse_arguments(["--batch-size", "50"]).batch_size == 50


def test_defaults_come_from_configuration() -> None:
    arguments = parse_arguments([])
    assert arguments.max_attempts is None
    assert arguments.batch_size is None


def test_a_failure_prints_no_detail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode() -> None:
        raise RuntimeError("postgresql://user:hunter2@host/db is unreachable")

    monkeypatch.setattr("episignal_backend.retrieve_runner._run", lambda _: explode())
    assert main([]) == 1
    captured = capsys.readouterr()
    assert "hunter2" not in captured.err
    assert "hunter2" not in captured.out
