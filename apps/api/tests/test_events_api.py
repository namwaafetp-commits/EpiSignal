from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

from episignal_api.dependencies import (
    get_dashboard_events_page,
    get_event_page,
    get_session,
)
from episignal_api.factory import create_app
from episignal_api.routes import events as events_route
from episignal_backend.config import Settings
from episignal_backend.db.types import (
    EventStatus,
    EventType,
    VerificationStatus,
)
from episignal_backend.events.read import (
    DashboardEventItem,
    DashboardEventPage,
    EventDetail,
    EventListItem,
    EventListPage,
    EventObservationItem,
    EventSourceItem,
    EventSummaryItem,
)
from fastapi.testclient import TestClient

TEST_SETTINGS = Settings(
    database_url="postgresql://test:test@localhost/test",
    _env_file=None,
)

NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)
PUBLIC_ID = "EVT-2026-00042"


def _list_item() -> EventListItem:
    return EventListItem(
        public_id=PUBLIC_ID,
        headline="Dengue outbreak in Chiang Mai",
        summary="Ongoing dengue outbreak in Chiang Mai.",
        disease="Dengue",
        event_type=EventType.OUTBREAK.value,
        status=EventStatus.ONGOING.value,
        verification_status=VerificationStatus.HIGH_CREDIBILITY.value,
        country_code="TH",
        admin1="Chiang Mai",
        admin2=None,
        first_reported_at=NOW,
        latest_report_at=NOW,
        article_count=3,
        last_summarized_at=NOW,
    )


def test_events_list_endpoint_returns_shaped_json() -> None:
    page = EventListPage(items=(_list_item(),), total=1, limit=20, offset=0)
    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_event_page] = lambda: page

    response = TestClient(app).get("/api/v1/events?disease=dengue&country=TH")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["public_id"] == PUBLIC_ID
    assert item["headline"] == "Dengue outbreak in Chiang Mai"
    assert item["disease"] == "Dengue"
    assert item["status"] == "ongoing"
    assert item["verification_status"] == "high_credibility"
    assert item["article_count"] == 3
    # No raw text, prompt, or patient fields leak onto the public surface.
    assert "raw_text" not in response.text
    assert "patient" not in response.text


def test_dashboard_endpoint_returns_summarized_event_map_fields() -> None:
    page = DashboardEventPage(
        items=(
            DashboardEventItem(
                public_id=PUBLIC_ID,
                headline="Dengue outbreak in Chiang Mai",
                summary="Ongoing dengue outbreak in Chiang Mai.",
                disease="Dengue",
                event_type=EventType.OUTBREAK.value,
                status=EventStatus.ONGOING.value,
                country_code="TH",
                admin1="Chiang Mai",
                first_reported_at=NOW,
                latest_report_at=NOW,
                article_count=3,
                last_summarized_at=NOW,
                latitude=18.7883,
                longitude=98.9853,
                map_level="admin1",
            ),
        ),
        total=1,
    )
    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_dashboard_events_page] = lambda: page

    response = TestClient(app).get("/api/v1/events/dashboard")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["admin1"] == "Chiang Mai"
    assert data["items"][0]["map_level"] == "admin1"
    assert data["items"][0]["latitude"] == 18.7883


def test_accepted_summary_status_is_visible_on_list_and_detail_endpoints() -> None:
    state = {"status": EventStatus.MONITORING.value}
    detail = EventDetail(
        public_id=PUBLIC_ID,
        headline=None,
        summary=None,
        disease="Dengue",
        event_type=EventType.OUTBREAK.value,
        status=EventStatus.MONITORING.value,
        verification_status=VerificationStatus.SIGNAL.value,
        country_code="TH",
        admin1="Chiang Mai",
        admin2=None,
        first_reported_at=NOW,
        latest_report_at=NOW,
        article_count=1,
        last_summarized_at=None,
        early_signal_score=None,
        evidence_score=None,
        sources=(),
        observations=(),
        summaries=(),
    )
    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_event_page] = lambda: EventListPage(
        items=(replace(_list_item(), status=state["status"]),),
        total=1,
        limit=20,
        offset=0,
    )
    app.dependency_overrides[get_session] = lambda: object()
    original_detail = events_route.query_event_detail
    events_route.query_event_detail = lambda session, public_id: replace(  # type: ignore[assignment]
        detail,
        status=state["status"],
    )
    try:
        # This is the API seam after the repository has accepted the summary
        # and changed the event from monitoring to ongoing.
        state["status"] = EventStatus.ONGOING.value
        list_response = TestClient(app).get("/api/v1/events")
        detail_response = TestClient(app).get(f"/api/v1/events/{PUBLIC_ID}")
    finally:
        events_route.query_event_detail = original_detail

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["status"] == EventStatus.ONGOING.value
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == EventStatus.ONGOING.value


def test_event_detail_endpoint_returns_sources_observations_and_summaries() -> None:
    detail = EventDetail(
        public_id=PUBLIC_ID,
        headline="Dengue outbreak in Chiang Mai",
        summary="Ongoing dengue outbreak in Chiang Mai.",
        disease="Dengue",
        event_type=EventType.OUTBREAK.value,
        status=EventStatus.ONGOING.value,
        verification_status=VerificationStatus.HIGH_CREDIBILITY.value,
        country_code="TH",
        admin1="Chiang Mai",
        admin2=None,
        first_reported_at=NOW,
        latest_report_at=NOW,
        article_count=3,
        last_summarized_at=NOW,
        early_signal_score=0.8,
        evidence_score=0.7,
        sources=(
            EventSourceItem(
                signal_id=uuid4(),
                source_name="Chiang Mai Provincial Health Office",
                is_official=True,
                credibility_tier="official",
                title="Dengue cases rise in Chiang Mai",
                url="https://health.example.org/report/1",
                published_at=NOW,
                first_seen_at=NOW,
                relationship_type="initial_report",
                is_primary=True,
            ),
        ),
        observations=(
            EventObservationItem(
                observation_date=date(2026, 8, 25),
                reported_at=NOW,
                suspected_cases=None,
                probable_cases=None,
                confirmed_cases=42,
                total_cases=42,
                new_cases=None,
                deaths=2,
                new_deaths=None,
                hospitalizations=None,
                notes=None,
                extraction_confidence=0.9,
            ),
        ),
        summaries=(
            EventSummaryItem(
                version=1,
                headline="Dengue outbreak in Chiang Mai",
                summary="Ongoing dengue outbreak in Chiang Mai.",
                status=EventStatus.ONGOING.value,
                latest_development="Case count rose to 68.",
                uncertainties=["Reporting may lag."],
                model_id="deepseek/deepseek-v4-flash-0731",
                created_at=NOW,
            ),
        ),
    )

    app = create_app(TEST_SETTINGS)

    class _FakeSession:
        pass

    app.dependency_overrides[get_session] = lambda: _FakeSession()
    original_detail = events_route.query_event_detail
    events_route.query_event_detail = lambda session, public_id: detail  # type: ignore[assignment]
    try:
        response = TestClient(app).get(f"/api/v1/events/{PUBLIC_ID}")
    finally:
        events_route.query_event_detail = original_detail

    assert response.status_code == 200
    data = response.json()
    assert data["public_id"] == PUBLIC_ID
    assert data["headline"] == "Dengue outbreak in Chiang Mai"
    assert data["status"] == "ongoing"
    assert len(data["sources"]) == 1
    assert data["sources"][0]["source_name"] == "Chiang Mai Provincial Health Office"
    assert data["sources"][0]["url"] == "https://health.example.org/report/1"
    assert len(data["observations"]) == 1
    assert data["observations"][0]["confirmed_cases"] == 42
    assert data["observations"][0]["deaths"] == 2
    assert len(data["summaries"]) == 1
    assert data["summaries"][0]["latest_development"] == "Case count rose to 68."
    # Publication datetime is always visible on sources.
    assert data["sources"][0]["published_at"] is not None


def test_event_detail_endpoint_404s_for_an_unknown_event() -> None:
    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_session] = lambda: object()
    original_detail = events_route.query_event_detail
    events_route.query_event_detail = lambda session, public_id: None  # type: ignore[assignment]
    try:
        response = TestClient(app).get("/api/v1/events/EVT-NOPE")
    finally:
        events_route.query_event_detail = original_detail

    assert response.status_code == 404


def test_event_sources_endpoint_returns_traceable_links() -> None:
    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_session] = lambda: object()
    original = events_route.query_event_sources
    events_route.query_event_sources = lambda session, public_id: (  # type: ignore[assignment]
        EventSourceItem(
            signal_id=uuid4(),
            source_name="Reuters",
            is_official=False,
            credibility_tier="high",
            title="Chiang Mai dengue cases climb",
            url="https://reuters.example/story/1",
            published_at=NOW,
            first_seen_at=NOW,
            relationship_type="update",
            is_primary=False,
        ),
    )
    try:
        response = TestClient(app).get(f"/api/v1/events/{PUBLIC_ID}/sources")
    finally:
        events_route.query_event_sources = original

    assert response.status_code == 200
    data = response.json()
    assert data[0]["title"] == "Chiang Mai dengue cases climb"
    assert data[0]["relationship_type"] == "update"
    assert data[0]["published_at"] is not None


def test_event_observations_endpoint_returns_observation_history() -> None:
    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_session] = lambda: object()
    original = events_route.query_event_observations
    events_route.query_event_observations = lambda session, public_id: (  # type: ignore[assignment]
        EventObservationItem(
            observation_date=date(2026, 8, 25),
            reported_at=NOW,
            suspected_cases=None,
            probable_cases=None,
            confirmed_cases=42,
            total_cases=42,
            new_cases=None,
            deaths=2,
            new_deaths=None,
            hospitalizations=None,
            notes=None,
            extraction_confidence=0.9,
        ),
        EventObservationItem(
            observation_date=date(2026, 8, 27),
            reported_at=NOW,
            suspected_cases=None,
            probable_cases=None,
            confirmed_cases=68,
            total_cases=68,
            new_cases=None,
            deaths=3,
            new_deaths=1,
            hospitalizations=None,
            notes=None,
            extraction_confidence=0.9,
        ),
    )
    try:
        response = TestClient(app).get(f"/api/v1/events/{PUBLIC_ID}/observations")
    finally:
        events_route.query_event_observations = original

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["confirmed_cases"] == 42
    assert data[1]["confirmed_cases"] == 68
    # History is preserved: the older value is never overwritten.
    assert [obs["confirmed_cases"] for obs in data] == [42, 68]
