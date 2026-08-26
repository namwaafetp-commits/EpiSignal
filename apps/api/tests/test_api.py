import os
import subprocess
import sys

import pytest
from episignal_api.dependencies import get_database_health
from episignal_api.factory import create_app
from episignal_backend.config import Settings
from episignal_backend.health import DatabaseHealth
from fastapi import FastAPI
from fastapi.testclient import TestClient

TEST_SETTINGS = Settings(
    database_url="postgresql://test:test@localhost/test",
    _env_file=None,
)


def make_app() -> FastAPI:
    return create_app(TEST_SETTINGS)


def test_liveness_does_not_require_database() -> None:
    client = TestClient(make_app())
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_returns_503_for_database_failure() -> None:
    app = make_app()
    app.dependency_overrides[get_database_health] = lambda: DatabaseHealth(
        database="down", postgis="unknown"
    )
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "components": {"database": "down", "postgis": "unknown"},
        "error_code": "DATABASE_NOT_READY",
    }


def test_readiness_returns_component_success() -> None:
    app = make_app()
    app.dependency_overrides[get_database_health] = lambda: DatabaseHealth(
        database="up", postgis="up"
    )
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "components": {"database": "up", "postgis": "up"},
    }


def test_version_endpoint_is_namespaced() -> None:
    response = TestClient(make_app()).get("/api/v1")
    assert response.status_code == 200
    assert response.json() == {"name": "EpiSignal API", "version": "0.1.0"}


def test_valid_inbound_request_id_is_propagated() -> None:
    request_id = "b4caace5-3afb-4a43-b2d8-ec0d8d5042ca"
    response = TestClient(make_app()).get("/health/live", headers={"X-Request-ID": request_id})
    assert response.headers["X-Request-ID"] == request_id


def test_invalid_request_id_is_replaced() -> None:
    response = TestClient(make_app()).get("/health/live", headers={"X-Request-ID": "not-a-uuid"})
    assert response.headers["X-Request-ID"] != "not-a-uuid"


def test_openapi_and_docs_are_available() -> None:
    client = TestClient(make_app())
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_production_entrypoint_fails_safely_without_database_url(tmp_path) -> None:
    environment = os.environ.copy()
    environment.pop("EPISIGNAL_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-c", "import episignal_api.main"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "EPISIGNAL_DATABASE_URL" in result.stderr
    assert "postgresql://" not in result.stderr


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("EPISIGNAL_DATABASE_URL", "sqlite:///private.db"),
        ("EPISIGNAL_API_PORT", "not-a-port"),
    ],
)
def test_production_entrypoint_names_actual_invalid_setting(
    tmp_path, setting: str, value: str
) -> None:
    environment = os.environ.copy()
    environment["EPISIGNAL_DATABASE_URL"] = "postgresql://test:test@localhost/test"
    environment[setting] = value
    result = subprocess.run(
        [sys.executable, "-c", "import episignal_api.main"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert setting in result.stderr
    assert value not in result.stderr


def test_unexpected_error_is_sanitized_and_correlated(caplog) -> None:
    app = make_app()

    @app.get("/explode")
    def explode() -> None:
        raise RuntimeError("private database detail")

    response = TestClient(app, raise_server_exceptions=False).get("/explode")
    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_SERVER_ERROR"
    assert "private database detail" not in response.text
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert response.headers["X-Request-ID"] in caplog.text
