from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from episignal_backend import discover_runner
from episignal_backend.ingestion.discovery import DiscoveryResult
from episignal_backend.schedule import stages
from episignal_backend.schedule.documents import DiscoveryWindow, PipelineCohort, StageName
from episignal_backend.schedule.run import run_chain


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


def _run_scheduled_discovery(
    monkeypatch: pytest.MonkeyPatch, result: DiscoveryResult
) -> dict[str, object]:
    class Client:
        def __init__(self, **kwargs: object) -> None:
            pass

    class Connector:
        def __init__(self, *, ngram: object, fetcher: object) -> None:
            pass

    monkeypatch.setattr(stages, "get_settings", _settings)
    monkeypatch.setattr(stages, "GdeltNgramClient", Client)
    monkeypatch.setattr(stages, "GdeltConnector", Connector)
    monkeypatch.setattr(stages, "session_scope", lambda: nullcontext(None))
    monkeypatch.setattr(stages, "SqlAlchemyDiscoveryRepository", lambda session: object())
    monkeypatch.setattr(stages, "run_discovery", lambda repository, connector, **kwargs: result)

    return dict(
        stages._discover(
            DiscoveryWindow(
                start=datetime(2026, 9, 10, 0, tzinfo=UTC),
                end=datetime(2026, 9, 10, 1, tzinfo=UTC),
            ),
            PipelineCohort(),
        )
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


@pytest.mark.parametrize(
    ("provider_status", "rules_succeeded", "rules_failed", "expected_ok", "expected_error"),
    (
        ("healthy", 62, 0, True, None),
        ("partial_degradation", 61, 1, False, "DiscoveryPartialDegradation"),
        ("unavailable", 0, 0, False, "DiscoveryUnavailable"),
    ),
)
def test_batch_provider_status_is_authoritative_for_discovery_stage(
    monkeypatch: pytest.MonkeyPatch,
    provider_status: str,
    rules_succeeded: int,
    rules_failed: int,
    expected_ok: bool,
    expected_error: str | None,
) -> None:
    counts = _run_scheduled_discovery(
        monkeypatch,
        DiscoveryResult(
            rules_run=62,
            rules_attempted=62,
            rules_succeeded=rules_succeeded,
            rules_failed=rules_failed,
            provider_status=provider_status,
            discovered=0,
        ),
    )

    outcome = run_chain((StageName.DISCOVER,), {StageName.DISCOVER: lambda: counts})

    assert outcome.outcomes[0].ok is expected_ok
    assert outcome.outcomes[0].error == expected_error


def test_legacy_doc_all_rules_failed_remains_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counts = _run_scheduled_discovery(
        monkeypatch,
        DiscoveryResult(
            rules_run=8,
            rules_attempted=8,
            rules_succeeded=0,
            rules_failed=8,
            provider_status="healthy",
        ),
    )

    outcome = run_chain((StageName.DISCOVER,), {StageName.DISCOVER: lambda: counts})

    assert outcome.outcomes[0].ok is False
    assert outcome.outcomes[0].error == "DiscoveryUnavailable"
