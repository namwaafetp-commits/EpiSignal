"""Tests for manual review queue API endpoints."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from episignal_api.dependencies import get_review_queue_page, get_review_resolver
from episignal_api.factory import create_app
from episignal_backend.config import Settings
from episignal_backend.db.types import (
    LocationRole,
    Precision,
    ProcessingStatus,
    ReviewReason,
    ReviewResolution,
    VerificationStatus,
)
from episignal_backend.review.documents import (
    DismissCommand,
    LinkEventCommand,
    ReviewActionNotAllowed,
    ReviewAlreadyResolved,
    ReviewCandidateEvent,
    ReviewCaseNotFound,
    ReviewCaseResult,
    ReviewDiseaseOption,
    ReviewQueueItem,
    ReviewQueuePage,
    ReviewSignalLocation,
    ReviewTargetStale,
)

TEST_SETTINGS = Settings(
    database_url="postgresql://test:test@localhost/test",
    review_admin_token=SecretStr("test-admin-token"),
    _env_file=None,
)


def test_get_review_queue_requires_authentication() -> None:
    app = create_app(TEST_SETTINGS)
    client = TestClient(app)

    response = client.get("/api/v1/admin/reviews")
    assert response.status_code == 401


def test_get_review_queue_returns_expected_payload() -> None:
    now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
    case_id = uuid4()
    signal_id = uuid4()
    disease_id = uuid4()
    event_id = uuid4()

    item = ReviewQueueItem(
        case_id=case_id,
        signal_id=signal_id,
        reason=ReviewReason.EVENT_MATCH_AMBIGUOUS,
        opened_at=now,
        title="Suspected Cholera outbreak reported in Sanaa",
        source_name="Yemen Health News",
        source_url="https://news.example/cholera-sanaa",
        first_seen_at=now,
        retrieval_attempts=0,
        extracted_disease_text="cholera",
        canonical_disease="Cholera",
        locations=[
            ReviewSignalLocation(
                location_role=LocationRole.PRIMARY,
                precision=Precision.PLACE,
                country_name="Yemen",
                admin1_name="Sanaa",
                place_name="Sanaa City",
                resolved_name="Sanaa City, Sanaa, Yemen",
            ),
        ],
        candidate_events=[
            ReviewCandidateEvent(
                event_id=event_id,
                public_id="EVT-2026-0001",
                title="Cholera Outbreak - Sanaa 2026",
                verification_status=VerificationStatus.UNVERIFIED,
                match_score=0.78,
            ),
        ],
        allowed_resolutions=[
            ReviewResolution.LINK_EVENT,
            ReviewResolution.CREATE_EVENT,
            ReviewResolution.DISMISS,
        ],
    )
    page = ReviewQueuePage(
        items=[item],
        total_open_cases=1,
        disease_options=[
            ReviewDiseaseOption(
                id=disease_id,
                canonical_name="Cholera",
            ),
        ],
        limit=50,
        offset=0,
    )

    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_review_queue_page] = lambda: page

    client = TestClient(app)
    response = client.get(
        "/api/v1/admin/reviews",
        headers={"Authorization": "Bearer test-admin-token"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_open_cases"] == 1
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert len(data["items"]) == 1
    assert data["items"][0]["case_id"] == str(case_id)
    assert data["items"][0]["reason"] == "event_match_ambiguous"
    assert data["items"][0]["allowed_resolutions"] == ["link_event", "create_event", "dismiss"]
    assert len(data["items"][0]["candidate_events"]) == 1
    assert data["items"][0]["candidate_events"][0]["event_id"] == str(event_id)
    assert len(data["disease_options"]) == 1
    assert data["disease_options"][0]["id"] == str(disease_id)


def test_resolve_review_case_requires_authentication() -> None:
    case_id = uuid4()
    app = create_app(TEST_SETTINGS)
    client = TestClient(app)

    response = client.post(
        f"/api/v1/admin/reviews/{case_id}/resolve",
        json={"action": "dismiss", "note": "Duplicate signal"},
    )
    assert response.status_code == 401


def test_resolve_review_case_success() -> None:
    now = datetime(2026, 8, 29, 12, 0, 0, tzinfo=UTC)
    case_id = uuid4()
    signal_id = uuid4()
    event_id = uuid4()

    expected_result = ReviewCaseResult(
        case_id=case_id,
        signal_id=signal_id,
        resolution=ReviewResolution.LINK_EVENT,
        processing_status=ProcessingStatus.MATCHED,
        selected_disease_id=None,
        selected_event_id=event_id,
        resolved_at=now,
    )

    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_review_resolver] = lambda: lambda cid, cmd: expected_result

    client = TestClient(app)
    response = client.post(
        f"/api/v1/admin/reviews/{case_id}/resolve",
        headers={"Authorization": "Bearer test-admin-token"},
        json={"action": "link_event", "target_event_id": str(event_id), "note": "Confirmed link"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["case_id"] == str(case_id)
    assert data["resolution"] == "link_event"
    assert data["selected_event_id"] == str(event_id)


def test_resolve_review_case_not_found_returns_404() -> None:
    case_id = uuid4()

    def _raise_not_found(cid: UUID, cmd: object) -> None:
        raise ReviewCaseNotFound(cid)

    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_review_resolver] = lambda: _raise_not_found

    client = TestClient(app)
    response = client.post(
        f"/api/v1/admin/reviews/{case_id}/resolve",
        headers={"Authorization": "Bearer test-admin-token"},
        json={"action": "dismiss", "note": "Discarded"},
    )
    assert response.status_code == 404


def test_resolve_review_case_conflict_returns_409() -> None:
    case_id = uuid4()

    def _raise_already_resolved(cid: UUID, cmd: object) -> None:
        raise ReviewAlreadyResolved(cid)

    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_review_resolver] = lambda: _raise_already_resolved

    client = TestClient(app)
    response = client.post(
        f"/api/v1/admin/reviews/{case_id}/resolve",
        headers={"Authorization": "Bearer test-admin-token"},
        json={"action": "dismiss", "note": "Discarded"},
    )
    assert response.status_code == 409


def test_resolve_review_case_stale_target_returns_409() -> None:
    case_id = uuid4()
    target_id = uuid4()

    def _raise_stale(cid: UUID, cmd: object) -> None:
        raise ReviewTargetStale(target_id)

    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_review_resolver] = lambda: _raise_stale

    client = TestClient(app)
    response = client.post(
        f"/api/v1/admin/reviews/{case_id}/resolve",
        headers={"Authorization": "Bearer test-admin-token"},
        json={"action": "link_event", "target_event_id": str(target_id)},
    )
    assert response.status_code == 409


def test_resolve_review_case_invalid_action_returns_422() -> None:
    case_id = uuid4()

    def _raise_invalid_action(cid: UUID, cmd: object) -> None:
        raise ReviewActionNotAllowed(ReviewReason.RETRIEVAL_FAILED, ReviewResolution.LINK_EVENT)

    app = create_app(TEST_SETTINGS)
    app.dependency_overrides[get_review_resolver] = lambda: _raise_invalid_action

    client = TestClient(app)
    response = client.post(
        f"/api/v1/admin/reviews/{case_id}/resolve",
        headers={"Authorization": "Bearer test-admin-token"},
        json={"action": "link_event", "target_event_id": str(uuid4())},
    )
    assert response.status_code == 422
