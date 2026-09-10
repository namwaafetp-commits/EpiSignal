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
        gdelt_query_window_minutes=20,
        gdelt_max_articles_per_run=200,
    )


def test_standalone_discover_runner_wires_request_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Client:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class Connector:
        def __init__(self, *, search: object, fetcher: object) -> None:
            captured["search"] = search

    monkeypatch.setattr(discover_runner, "get_settings", _settings)
    monkeypatch.setattr(discover_runner, "GdeltDocClient", Client)
    monkeypatch.setattr(discover_runner, "GdeltConnector", Connector)
    monkeypatch.setattr(discover_runner, "session_scope", lambda: nullcontext(None))
    monkeypatch.setattr(
        discover_runner,
        "run_discovery",
        lambda repository, connector, **kwargs: DiscoveryResult(rules_run=1),
    )

    discover_runner._run(discover_runner.Arguments(window_minutes=None, max_articles=None))

    assert captured["request_delay_seconds"] == 3.25


def test_scheduled_discovery_wires_request_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Client:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class Connector:
        def __init__(self, *, search: object, fetcher: object) -> None:
            captured["search"] = search

    monkeypatch.setattr(stages, "get_settings", _settings)
    monkeypatch.setattr(stages, "GdeltDocClient", Client)
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

    assert captured["request_delay_seconds"] == 3.25
