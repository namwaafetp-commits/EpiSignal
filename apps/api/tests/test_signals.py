from datetime import UTC, datetime
from uuid import UUID

from episignal_api.dependencies import get_evidence_page
from episignal_api.factory import create_app
from episignal_backend.config import Settings
from episignal_backend.evidence import EvidencePage, EvidenceSignal
from fastapi.testclient import TestClient

TEST_SETTINGS = Settings(
    database_url="postgresql://test:test@localhost/test",
    _env_file=None,
)


def test_lists_recent_signals_with_exact_evidence_and_coverage() -> None:
    moment = datetime(2026, 8, 14, 15, 38, 29, tzinfo=UTC)
    evidence = EvidenceSignal(
        id=UUID("178cc906-edee-4b01-9efb-b230c00a397a"),
        source_name="WHO Disease Outbreak News",
        title="Ebola disease - Democratic Republic of the Congo",
        raw_text="4665 confirmed cases.",
        url="https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615",
        published_at=moment,
        retrieved_at=moment,
    )
    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_evidence_page] = lambda: EvidencePage(
        items=(evidence,),
        total=12,
        source_count=1,
        limit=20,
        offset=0,
    )

    response = TestClient(app).get("/api/v1/signals")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": "178cc906-edee-4b01-9efb-b230c00a397a",
                "source_name": "WHO Disease Outbreak News",
                "title": "Ebola disease - Democratic Republic of the Congo",
                "raw_text": "4665 confirmed cases.",
                "url": ("https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615"),
                "published_at": "2026-08-14T15:38:29Z",
                "retrieved_at": "2026-08-14T15:38:29Z",
            }
        ],
        "total": 12,
        "source_count": 1,
        "limit": 20,
        "offset": 0,
    }
