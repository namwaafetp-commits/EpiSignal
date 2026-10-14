from episignal_api.factory import create_app
from episignal_backend.config import Settings


def test_openapi_exposes_public_routes() -> None:
    settings = Settings(
        database_url="postgresql://openapi:openapi@localhost/openapi",
        _env_file=None,
    )
    paths = set(create_app(settings).openapi()["paths"])
    assert paths == {
        "/health/live",
        "/health/ready",
        "/api/v1",
        "/api/v1/signals",
        "/api/v1/radar",
        "/api/v1/events",
        "/api/v1/events/dashboard",
        "/api/v1/events/{public_id}",
        "/api/v1/events/{public_id}/sources",
        "/api/v1/events/{public_id}/observations",
        "/api/v1/admin/pipeline-runs",
        "/api/v1/admin/reviews",
        "/api/v1/admin/reviews/{case_id}/resolve",
    }
