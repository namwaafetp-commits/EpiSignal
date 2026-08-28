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
        "/api/v1/admin/pipeline-runs",
    }
