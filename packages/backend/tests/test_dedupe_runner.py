from typing import Any

import pytest
from episignal_backend import dedupe_runner
from episignal_backend.ingestion.dedupe import DedupeResult


def test_arguments_default_to_none() -> None:
    arguments = dedupe_runner.parse_arguments([])

    assert arguments.batch_size is None
    assert arguments.window_hours is None


def test_arguments_are_parsed_past_the_pnpm_separator() -> None:
    arguments = dedupe_runner.parse_arguments(["--", "--batch-size", "10"])

    assert arguments.batch_size == 10


def test_counts_are_printed_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(arguments: Any) -> DedupeResult:
        return DedupeResult(examined=4, primaries=1, duplicates=3, failed=0)

    monkeypatch.setattr(dedupe_runner, "_run", fake_run)

    assert dedupe_runner.main([]) == 0
    assert "examined=4 primaries=1 duplicates=3 failed=0" in capsys.readouterr().out


def test_a_failure_is_reported_without_detail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(arguments: Any) -> DedupeResult:
        raise RuntimeError("postgresql://user:secret@host/db is unreachable")

    monkeypatch.setattr(dedupe_runner, "_run", fake_run)

    assert dedupe_runner.main([]) == 1
    captured = capsys.readouterr()
    assert "secret" not in captured.err
    assert "Deduplication failed" in captured.err
