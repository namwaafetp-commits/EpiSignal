import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from episignal_api.factory import create_app
from episignal_backend.config import Settings
from episignal_backend.db import session as database
from episignal_backend.db.types import EventStatus, EventType, HostSector
from fastapi.testclient import TestClient


@pytest.fixture
def dashboard_database(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = SimpleNamespace(
        available=True, headline="Stored outbreak", sessions=0, delay=0.0, blocked=None
    )
    reported_at = datetime(2026, 10, 4, 16, 2, tzinfo=UTC)
    event_id = uuid4()

    class Session:
        def __init__(self) -> None:
            state.sessions += 1
            event = SimpleNamespace(
                id=event_id,
                public_id="EVT-2026-00042",
                headline=state.headline,
                summary="Stored evidence summary.",
                event_type=EventType.OUTBREAK,
                status=EventStatus.MONITORING,
                country_code=None,
                admin1=None,
                first_signal_at=reported_at,
                last_updated_at=reported_at,
                article_count=1,
                last_summarized_at=reported_at,
            )
            self.results = [[(event, "Dengue", "dengue")], [(event_id, HostSector.HUMAN)]]

        def execute(self, statement: Any) -> Any:
            if state.blocked is not None:
                started, release = state.blocked
                started.set()
                if not release.wait(timeout=10):
                    raise TimeoutError("Test database read was not released")
            if not state.available:
                time.sleep(state.delay)
                raise RuntimeError("Test database unavailable")
            rows = self.results.pop(0)
            return SimpleNamespace(all=lambda: rows)

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            pass

        def close(self) -> None:
            pass

    # Replace only the database boundary; exercise the real query and API shaping.
    monkeypatch.setattr(database, "get_session_factory", lambda: Session)
    return state


def client() -> TestClient:
    settings = Settings(database_url="postgresql://test:test@localhost/test", _env_file=None)
    return TestClient(create_app(settings), raise_server_exceptions=False)


def test_dashboard_reuses_recent_evidence_during_database_outage(
    dashboard_database: SimpleNamespace,
) -> None:
    api = client()
    first = api.get("/api/v1/events/dashboard")
    assert first.status_code == 200
    dashboard_database.available = False

    cached = api.get("/api/v1/events/dashboard")

    assert cached.status_code == 200
    assert cached.json() == first.json()
    assert cached.json()["items"][0]["last_summarized_at"] == "2026-10-04T16:02:00Z"


def test_dashboard_refreshes_after_expiry_and_does_not_cache_failures(
    dashboard_database: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [100.0]
    monkeypatch.setattr(
        "episignal_api.dashboard_cache.time", SimpleNamespace(monotonic=lambda: clock[0])
    )
    api = client()
    assert api.get("/api/v1/events/dashboard").status_code == 200
    dashboard_database.headline = "Updated outbreak"
    clock[0] = 159.0
    assert api.get("/api/v1/events/dashboard").json()["items"][0]["headline"] == "Stored outbreak"

    clock[0] = 160.0
    dashboard_database.available = False
    assert api.get("/api/v1/events/dashboard").status_code == 500
    dashboard_database.available = True
    refreshed = api.get("/api/v1/events/dashboard")
    assert refreshed.status_code == 200
    assert refreshed.json()["items"][0]["headline"] == "Updated outbreak"


def test_a_slow_filter_refresh_does_not_block_cached_dashboard_or_liveness(
    dashboard_database: SimpleNamespace,
) -> None:
    started, release = Event(), Event()
    with client() as api, ThreadPoolExecutor(max_workers=2) as pool:
        assert api.get("/api/v1/events/dashboard").status_code == 200
        dashboard_database.blocked = (started, release)
        cold = pool.submit(api.get, "/api/v1/events/dashboard?host_sector=human")
        try:
            assert started.wait(timeout=5)
            hot = pool.submit(api.get, "/api/v1/events/dashboard")
            assert hot.result(timeout=2).status_code == 200
            assert api.get("/health/live").json() == {"status": "alive"}
        finally:
            release.set()
        assert cold.result(timeout=5).status_code == 200


def test_dashboard_cache_capacity_evicts_old_filters(
    dashboard_database: SimpleNamespace,
) -> None:
    with client() as api:
        assert api.get("/api/v1/events/dashboard").status_code == 200
        for index in range(33):
            assert (
                api.get(f"/api/v1/events/dashboard?disease_group=test-{index}").status_code == 200
            )

        dashboard_database.available = False
        assert api.get("/api/v1/events/dashboard?disease_group=test-32").status_code == 200
        assert api.get("/api/v1/events/dashboard").status_code == 500


def test_dashboard_filters_and_app_instances_do_not_share_cached_results(
    dashboard_database: SimpleNamespace,
) -> None:
    api = client()
    assert api.get("/api/v1/events/dashboard?host_sector=human").json()["total"] == 1
    assert api.get("/api/v1/events/dashboard?host_sector=animal").json()["total"] == 0
    assert api.get("/api/v1/events/dashboard?disease_group=unknown").json()["total"] == 0
    assert api.get("/api/v1/events/dashboard").json()["total"] == 1

    dashboard_database.available = False
    assert client().get("/api/v1/events/dashboard").status_code == 500


def test_concurrent_dashboard_failures_share_one_database_attempt_then_allow_retry(
    dashboard_database: SimpleNamespace,
) -> None:
    dashboard_database.available = False
    dashboard_database.delay = 1.0
    api = client()
    callers = Barrier(6)

    def request() -> int:
        callers.wait(timeout=10)
        return api.get("/api/v1/events/dashboard").status_code

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: request(), range(6)))

    assert responses == [500] * 6
    # Database attempts are the external resource this concurrency contract bounds.
    assert dashboard_database.sessions == 1
    dashboard_database.available = True
    assert api.get("/api/v1/events/dashboard").status_code == 200
