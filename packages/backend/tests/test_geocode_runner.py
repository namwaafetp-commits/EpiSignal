import json
from pathlib import Path
from typing import Any

from episignal_backend.geocode_runner import main, parse_arguments


def test_it_defaults_to_the_fresh_pass() -> None:
    arguments = parse_arguments([])
    assert arguments.limit is None
    assert arguments.stale is False


def test_it_accepts_a_limit_and_the_stale_flag() -> None:
    arguments = parse_arguments(["--limit", "50", "--stale"])
    assert arguments.limit == 50
    assert arguments.stale is True


def test_it_ignores_the_bare_separator_pnpm_passes_through() -> None:
    assert parse_arguments(["--", "--limit", "5"]).limit == 5


def test_a_failure_prints_the_exception_type_and_nothing_else(
    monkeypatch: Any, capsys: Any
) -> None:
    def explode(_: Any) -> None:
        raise RuntimeError("postgresql://user:secret@host/db")

    monkeypatch.setattr("episignal_backend.geocode_runner._run", explode)
    assert main([]) == 1
    captured = capsys.readouterr()
    assert "secret" not in captured.err
    assert "RuntimeError" in captured.err


def test_a_successful_run_prints_counts_only(monkeypatch: Any, capsys: Any) -> None:
    from episignal_backend.geocode.locate import GeocodingResult

    monkeypatch.setattr(
        "episignal_backend.geocode_runner._run",
        lambda _: GeocodingResult(examined=3, located=4, unresolved=1, locations=5),
    )
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "examined=3" in captured.out
    assert "located=4" in captured.out
    assert "unresolved=1" in captured.out


def test_the_workspace_script_is_wired() -> None:
    package = json.loads(Path("package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["geocode:signals"] == (
        "uv run --package episignal-backend python -m episignal_backend.geocode_runner"
    )
