from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from episignal_backend import discover_runner
from episignal_backend.ingestion.discovery import DiscoveryResult
from episignal_backend.schedule import stages
from episignal_backend.schedule.documents import DiscoveryWindow, PipelineCohort


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        gdelt_request_delay_seconds=3.25,
        gdelt_article_delay_seconds=0.0,
        gdelt_user_agent="test",
        gdelt_article_timeout_seconds=10.0,
        gdelt_ngram_timeout_seconds=30.0,
        gdelt_ngram_max_download_bytes=1_500_000_000,
        gdelt_ngram_max_catchup_minutes=360,
        gdelt_ngram_max_batches=64,
        gdelt_query_window_minutes=20,
        gdelt_max_articles_per_run=200,
    )


def test_standalone_discover_runner_wires_ngram_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Client:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class Connector:
        def __init__(self, *, ngram: object, fetcher: object) -> None:
            captured["ngram"] = ngram

    monkeypatch.setattr(discover_runner, "get_settings", _settings)
    monkeypatch.setattr(discover_runner, "GdeltNgramClient", Client)
    monkeypatch.setattr(discover_runner, "GdeltConnector", Connector)
    monkeypatch.setattr(discover_runner, "session_scope", lambda: nullcontext(None))
    monkeypatch.setattr(
        discover_runner,
        "run_discovery",
        lambda repository, connector, **kwargs: DiscoveryResult(rules_run=1),
    )

    discover_runner._run(discover_runner.Arguments(window_minutes=None, max_articles=None))

    assert captured["timeout_seconds"] == 30.0
    assert captured["max_download_bytes"] == 1_500_000_000


def test_scheduled_discovery_wires_ngram_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Client:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class Connector:
        def __init__(self, *, ngram: object, fetcher: object) -> None:
            captured["ngram"] = ngram

    monkeypatch.setattr(stages, "get_settings", _settings)
    monkeypatch.setattr(stages, "GdeltNgramClient", Client)
    monkeypatch.setattr(stages, "GdeltConnector", Connector)
    monkeypatch.setattr(stages, "session_scope", lambda: nullcontext(None))
    monkeypatch.setattr(
        stages,
        "SqlAlchemyDiscoveryRepository",
        lambda session: object(),
    )
    monkeypatch.setattr(
        stages,
        "run_discovery",
        lambda repository, connector, **kwargs: DiscoveryResult(
            rules_run=1, rules_attempted=1, rules_succeeded=1
        ),
    )

    stages._discover(
        DiscoveryWindow(
            start=datetime(2026, 9, 10, 0, tzinfo=UTC),
            end=datetime(2026, 9, 10, 1, tzinfo=UTC),
        ),
        PipelineCohort(),
    )

    assert captured["timeout_seconds"] == 30.0
    assert captured["max_download_bytes"] == 1_500_000_000
