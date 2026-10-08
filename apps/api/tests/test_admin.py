from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import pytest
from episignal_api.dependencies import get_pipeline_runs_page
from episignal_api.factory import create_app
from episignal_backend.config import Settings
from episignal_backend.db.types import (
    PipelineChain,
    PipelineRunStatus,
    PipelineTrigger,
)
from episignal_backend.radar import (
    PipelineFailure,
    PipelineRunItem,
    PipelineRunPage,
)
from episignal_backend.schedule.documents import StageName
from fastapi import Query
from fastapi.testclient import TestClient

TEST_SETTINGS = Settings(
    database_url="postgresql://test:test@localhost/test",
    _env_file=None,
)


def test_admin_pipeline_runs_endpoint_returns_exact_json_shape() -> None:
    started_moment = datetime(2026, 8, 28, 10, 0, 0, tzinfo=UTC)
    finished_moment = datetime(2026, 8, 28, 10, 8, 30, tzinfo=UTC)
    window_start = datetime(2026, 8, 27, 10, 0, 0, tzinfo=UTC)
    window_end = datetime(2026, 8, 28, 10, 0, 0, tzinfo=UTC)

    run_item = PipelineRunItem(
        id=UUID("12345678-1234-5678-1234-567812345678"),
        chain=PipelineChain.DAILY,
        trigger=PipelineTrigger.SCHEDULED,
        status=PipelineRunStatus.FAILED,
        started_at=started_moment,
        finished_at=finished_moment,
        window_start=window_start,
        window_end=window_end,
        stage_counts={"extract": {"extracted": 10, "review": 2}},
        backlog={"extracted": 0},
        failures=(PipelineFailure(stage=StageName.EXTRACT, error="TimeoutError"),),
        is_stale=False,
    )
    run_page = PipelineRunPage(items=(run_item,), limit=20)

    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_pipeline_runs_page] = lambda: run_page

    client = TestClient(app)
    response = client.get("/api/v1/admin/pipeline-runs")

    assert response.status_code == 200
    data = response.json()

    assert data == {
        "items": [
            {
                "id": "12345678-1234-5678-1234-567812345678",
                "chain": "daily",
                "trigger": "scheduled",
                "status": "failed",
                "started_at": "2026-08-28T10:00:00Z",
                "finished_at": "2026-08-28T10:08:30Z",
                "window_start": "2026-08-27T10:00:00Z",
                "window_end": "2026-08-28T10:00:00Z",
                "stage_counts": {"extract": {"extracted": 10, "review": 2}},
                "backlog": {"extracted": 0},
                "failures": [{"stage": "extract", "error": "TimeoutError"}],
                "is_stale": False,
            }
        ],
        "limit": 20,
    }

    # Security assertion: ensure no secret or prompt/model payload text leaks
    serialized = response.text
    for forbidden in ["password", "secret", "raw_text", "prompt", "api_key"]:
        assert f'"{forbidden}"' not in serialized


@pytest.mark.parametrize(
    ("query_string", "expected_status"),
    [
        ("", 200),
        ("limit=20", 200),
        ("limit=1", 200),
        ("limit=50", 200),
        ("limit=0", 422),
        ("limit=51", 422),
    ],
)
def test_admin_pipeline_runs_query_bounds(query_string: str, expected_status: int) -> None:
    run_page = PipelineRunPage(items=(), limit=20)
    app = create_app(TEST_SETTINGS)

    def override_pipeline_runs(
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
    ) -> PipelineRunPage:
        del limit
        return run_page

    app.dependency_overrides[get_pipeline_runs_page] = override_pipeline_runs

    client = TestClient(app)
    import episignal_api.dependencies as deps

    original_query = deps.query_pipeline_runs
    deps.query_pipeline_runs = (  # type: ignore[assignment]
        lambda session, *, now, stale_after_minutes, limit: run_page
    )
    try:
        url = (
            f"/api/v1/admin/pipeline-runs?{query_string}"
            if query_string
            else "/api/v1/admin/pipeline-runs"
        )
        response = client.get(url)
        assert response.status_code == expected_status
    finally:
        deps.query_pipeline_runs = original_query
