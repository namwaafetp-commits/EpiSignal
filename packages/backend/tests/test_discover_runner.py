import pytest
from episignal_backend.discover_runner import main, parse_arguments


def test_parses_an_explicit_window() -> None:
    assert parse_arguments(["--window-minutes", "45"]).window_minutes == 45


def test_parses_an_explicit_cap() -> None:
    assert parse_arguments(["--max-articles", "10"]).max_articles == 10


def test_defaults_come_from_configuration() -> None:
    arguments = parse_arguments([])
    assert arguments.window_minutes is None
    assert arguments.max_articles is None


def test_a_discovery_run_with_rules_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from episignal_backend.ingestion.discovery import DiscoveryResult

    monkeypatch.setattr(
        "episignal_backend.discover_runner._run",
        lambda _: DiscoveryResult(rules_run=3),
    )
    assert main([]) == 0


def test_a_failure_prints_no_detail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode() -> None:
        raise RuntimeError("postgresql://user:hunter2@host/db is unreachable")

    monkeypatch.setattr("episignal_backend.discover_runner._run", lambda _: explode())
    assert main([]) == 1
    captured = capsys.readouterr()
    # The connection string must never reach a console or a log scrape.
    assert "hunter2" not in captured.err
    assert "hunter2" not in captured.out
