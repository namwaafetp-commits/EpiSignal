from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

import pytest
from episignal_api.dependencies import get_radar_page
from episignal_api.factory import create_app
from episignal_backend.ai.schema import BriefPoint, BriefSlot
from episignal_backend.config import Settings
from episignal_backend.db.types import (
    CredibilityTier,
    LocationRole,
    Precision,
    ProcessingStatus,
    SignalType,
    VerificationStatus,
)
from episignal_backend.radar import (
    EventContextStatus,
    RadarEventContext,
    RadarEventGroup,
    RadarItem,
    RadarLocation,
    RadarPage,
    RadarSource,
)
from fastapi import Query
from fastapi.testclient import TestClient

TEST_SETTINGS = Settings(
    database_url="postgresql://test:test@localhost/test",
    _env_file=None,
)


def test_radar_endpoint_returns_exact_json_shape_and_no_leaked_fields() -> None:
    published_moment = datetime(2026, 8, 28, 10, 0, 0, tzinfo=UTC)
    first_seen_moment = datetime(2026, 8, 28, 10, 5, 0, tzinfo=UTC)
    window_start = datetime(2026, 8, 26, 12, 0, 0, tzinfo=UTC)
    window_end = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)

    source = RadarSource(
        name="WHO AFRO",
        url="https://afro.who.int/report/123",
        is_official=True,
        credibility_tier=CredibilityTier.OFFICIAL,
    )
    location = RadarLocation(
        role=LocationRole.PRIMARY,
        precision=Precision.ADMIN1,
        label="Luanda Province",
        country_code="AO",
        latitude=-8.8383,
        longitude=13.2344,
    )
    event = RadarEventContext(
        public_id="EVT-2026-00042",
        verification_status=VerificationStatus.OFFICIALLY_CONFIRMED,
        early_signal_score=0.88,
        evidence_score=0.94,
    )
    brief = (
        BriefPoint(
            slot=BriefSlot.WHAT_WHERE,
            text="Cholera outbreak reported in Luanda province.",
            reported=True,
        ),
        BriefPoint(
            slot=BriefSlot.COUNTS,
            text="120 suspected cases and 4 deaths.",
            reported=True,
        ),
        BriefPoint(
            slot=BriefSlot.TIMING,
            text="Cases reported between August 20 and August 27.",
            reported=True,
        ),
        BriefPoint(
            slot=BriefSlot.SPREAD,
            text="Spread observed across two municipal districts.",
            reported=True,
        ),
        BriefPoint(
            slot=BriefSlot.REPORTING,
            text="Reported by the Provincial Health Directorate.",
            reported=True,
        ),
    )
    item = RadarItem(
        id=UUID("24681357-1234-5678-9abc-def012345678"),
        title_english="Cholera outbreak in Luanda Province",
        brief=brief,
        signal_type=SignalType.OUTBREAK_REPORT,
        processing_status=ProcessingStatus.MATCHED,
        published_at=published_moment,
        first_seen_at=first_seen_moment,
        source=source,
        extraction_confidence=0.95,
        location=location,
        event_context_status=EventContextStatus.ATTACHED,
        event=event,
    )
    second_item = RadarItem(
        id=UUID("86421357-1234-5678-9abc-def012345678"),
        title_english="Cholera cluster in Cacuaco district",
        brief=brief,
        signal_type=SignalType.OUTBREAK_REPORT,
        processing_status=ProcessingStatus.MATCHED,
        published_at=None,
        first_seen_at=first_seen_moment,
        source=source,
        extraction_confidence=0.9,
        location=location,
        event_context_status=EventContextStatus.ATTACHED,
        event=event,
    )
    group = RadarEventGroup(
        event_public_id="EVT-2026-00042",
        event=event,
        signal_count=2,
        representative_title="Cholera outbreak in Luanda Province",
        representative_brief=brief,
        representative_location=location,
        representative_source=source,
        all_source_names=("WHO AFRO",),
        earliest_published_at=published_moment,
        latest_published_at=published_moment,
        first_seen_at=first_seen_moment,
    )
    radar_page = RadarPage(
        event_groups=(group,),
        items=(item, second_item),
        window_start=window_start,
        window_end=window_end,
        hours=48,
        limit=50,
    )

    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_radar_page] = lambda: radar_page

    client = TestClient(app)
    response = client.get("/api/v1/radar")

    assert response.status_code == 200
    data = response.json()

    assert data == {
        "event_groups": [
            {
                "event_public_id": "EVT-2026-00042",
                "event": {
                    "public_id": "EVT-2026-00042",
                    "verification_status": "officially_confirmed",
                    "early_signal_score": 0.88,
                    "evidence_score": 0.94,
                },
                "signal_count": 2,
                "representative_title": "Cholera outbreak in Luanda Province",
                "representative_brief": [
                    {
                        "slot": "what_where",
                        "text": "Cholera outbreak reported in Luanda province.",
                        "reported": True,
                    },
                    {
                        "slot": "counts",
                        "text": "120 suspected cases and 4 deaths.",
                        "reported": True,
                    },
                    {
                        "slot": "timing",
                        "text": "Cases reported between August 20 and August 27.",
                        "reported": True,
                    },
                    {
                        "slot": "spread",
                        "text": "Spread observed across two municipal districts.",
                        "reported": True,
                    },
                    {
                        "slot": "reporting",
                        "text": "Reported by the Provincial Health Directorate.",
                        "reported": True,
                    },
                ],
                "representative_location": {
                    "role": "primary",
                    "precision": "admin1",
                    "label": "Luanda Province",
                    "country_code": "AO",
                    "latitude": -8.8383,
                    "longitude": 13.2344,
                },
                "representative_source": {
                    "name": "WHO AFRO",
                    "url": "https://afro.who.int/report/123",
                    "is_official": True,
                    "credibility_tier": "official",
                },
                "all_source_names": ["WHO AFRO"],
                "earliest_published_at": "2026-08-28T10:00:00Z",
                "latest_published_at": "2026-08-28T10:00:00Z",
                "first_seen_at": "2026-08-28T10:05:00Z",
            }
        ],
        "items": [
            {
                "id": "24681357-1234-5678-9abc-def012345678",
                "title_english": "Cholera outbreak in Luanda Province",
                "brief": [
                    {
                        "slot": "what_where",
                        "text": "Cholera outbreak reported in Luanda province.",
                        "reported": True,
                    },
                    {
                        "slot": "counts",
                        "text": "120 suspected cases and 4 deaths.",
                        "reported": True,
                    },
                    {
                        "slot": "timing",
                        "text": "Cases reported between August 20 and August 27.",
                        "reported": True,
                    },
                    {
                        "slot": "spread",
                        "text": "Spread observed across two municipal districts.",
                        "reported": True,
                    },
                    {
                        "slot": "reporting",
                        "text": "Reported by the Provincial Health Directorate.",
                        "reported": True,
                    },
                ],
                "signal_type": "outbreak_report",
                "processing_status": "matched",
                "published_at": "2026-08-28T10:00:00Z",
                "first_seen_at": "2026-08-28T10:05:00Z",
                "source": {
                    "name": "WHO AFRO",
                    "url": "https://afro.who.int/report/123",
                    "is_official": True,
                    "credibility_tier": "official",
                },
                "extraction_confidence": 0.95,
                "location": {
                    "role": "primary",
                    "precision": "admin1",
                    "label": "Luanda Province",
                    "country_code": "AO",
                    "latitude": -8.8383,
                    "longitude": 13.2344,
                },
                "event_context_status": "attached",
                "event": {
                    "public_id": "EVT-2026-00042",
                    "verification_status": "officially_confirmed",
                    "early_signal_score": 0.88,
                    "evidence_score": 0.94,
                },
            },
            {
                "id": "86421357-1234-5678-9abc-def012345678",
                "title_english": "Cholera cluster in Cacuaco district",
                "brief": [
                    {
                        "slot": "what_where",
                        "text": "Cholera outbreak reported in Luanda province.",
                        "reported": True,
                    },
                    {
                        "slot": "counts",
                        "text": "120 suspected cases and 4 deaths.",
                        "reported": True,
                    },
                    {
                        "slot": "timing",
                        "text": "Cases reported between August 20 and August 27.",
                        "reported": True,
                    },
                    {
                        "slot": "spread",
                        "text": "Spread observed across two municipal districts.",
                        "reported": True,
                    },
                    {
                        "slot": "reporting",
                        "text": "Reported by the Provincial Health Directorate.",
                        "reported": True,
                    },
                ],
                "signal_type": "outbreak_report",
                "processing_status": "matched",
                "published_at": None,
                "first_seen_at": "2026-08-28T10:05:00Z",
                "source": {
                    "name": "WHO AFRO",
                    "url": "https://afro.who.int/report/123",
                    "is_official": True,
                    "credibility_tier": "official",
                },
                "extraction_confidence": 0.9,
                "location": {
                    "role": "primary",
                    "precision": "admin1",
                    "label": "Luanda Province",
                    "country_code": "AO",
                    "latitude": -8.8383,
                    "longitude": 13.2344,
                },
                "event_context_status": "attached",
                "event": {
                    "public_id": "EVT-2026-00042",
                    "verification_status": "officially_confirmed",
                    "early_signal_score": 0.88,
                    "evidence_score": 0.94,
                },
            },
        ],
        "window_start": "2026-08-26T12:00:00Z",
        "window_end": "2026-08-28T12:00:00Z",
        "hours": 48,
        "limit": 50,
    }

    # Security assertion: ensure no raw_text, summary, prompt, model, or patient fields leak
    serialized_text = response.text
    forbidden_keys = ["raw_text", "summary", "prompt", "model", "patient", "content_hash"]
    for forbidden in forbidden_keys:
        assert f'"{forbidden}"' not in serialized_text


@pytest.mark.parametrize(
    ("query_string", "expected_status"),
    [
        ("hours=48&limit=50", 200),
        ("hours=1&limit=1", 200),
        ("hours=168&limit=100", 200),
        ("hours=0&limit=50", 422),
        ("hours=169&limit=50", 422),
        ("hours=48&limit=0", 422),
        ("hours=48&limit=101", 422),
    ],
)
def test_radar_endpoint_query_bounds(query_string: str, expected_status: int) -> None:
    now = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
    radar_page = RadarPage(
        event_groups=(),
        items=(),
        window_start=now,
        window_end=now,
        hours=48,
        limit=50,
    )
    app = create_app(TEST_SETTINGS)

    def override_radar(
        hours: Annotated[int, Query(ge=1, le=168)] = 48,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> RadarPage:
        del hours, limit
        return radar_page

    app.dependency_overrides[get_radar_page] = override_radar

    client = TestClient(app)
    # Monkeypatch query_radar in episignal_api.dependencies
    import episignal_api.dependencies as deps

    original_query = deps.query_radar
    deps.query_radar = lambda session, *, now, hours, limit: radar_page  # type: ignore[assignment]
    try:
        response = client.get(f"/api/v1/radar?{query_string}")
        assert response.status_code == expected_status
    finally:
        deps.query_radar = original_query
