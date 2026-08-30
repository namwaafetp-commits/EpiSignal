import json
from pathlib import Path
from typing import Any

from episignal_backend.event_runner import main, parse_arguments
from episignal_backend.events.assemble import AssemblySummary


def test_it_defaults_to_fresh_matching_pass() -> None:
    arguments = parse_arguments([])
    assert arguments.limit is None
    assert arguments.stale is False


def test_it_accepts_limit_and_stale_flag() -> None:
    arguments = parse_arguments(["--limit", "50", "--stale"])
    assert arguments.limit == 50
    assert arguments.stale is True


def test_it_ignores_bare_separator_passed_by_pnpm() -> None:
    assert parse_arguments(["--", "--limit", "10"]).limit == 10


def test_failure_prints_exception_type_without_secret_leak(monkeypatch: Any, capsys: Any) -> None:
    def explode(_: Any) -> None:
        raise RuntimeError("postgresql://user:secret@host/db")

    monkeypatch.setattr("episignal_backend.event_runner._run", explode)
    assert main([]) == 1
    captured = capsys.readouterr()
    assert "secret" not in captured.err
    assert "RuntimeError" in captured.err


def test_successful_run_prints_summary_counts(monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(
        "episignal_backend.event_runner._run",
        lambda _: AssemblySummary(
            signals_seen=5,
            clusters_built=2,
            events_created=1,
            signals_attached=3,
            signals_refused=1,
            unclusterable=0,
        ),
    )
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "seen=5" in captured.out
    assert "clusters=2" in captured.out
    assert "created=1" in captured.out
    assert "attached=3" in captured.out
    assert "refused=1" in captured.out
    assert "unclusterable=0" in captured.out


def test_the_workspace_script_is_wired_in_package_json() -> None:
    package = json.loads(Path("package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["match:events"] == (
        "uv run --package episignal-backend python -m episignal_backend.event_runner"
    )
