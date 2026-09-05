"""Calibration fixtures migrated to the deterministic identity contract."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from episignal_backend.db.types import CredibilityTier, LocationRole, Precision
from episignal_backend.events.cluster import build_clusters
from episignal_backend.events.documents import LocationForMatching, SignalForMatching
from episignal_backend.events.summarize import should_resummarize

FIXTURES = Path(__file__).parent / "fixtures" / "calibration"


def reports(name: str) -> tuple[SignalForMatching, ...]:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return tuple(
        SignalForMatching(
            signal_id=UUID(item["signal_id"]),
            disease_id=UUID(item["disease_id"]),
            source_id=uuid4(),
            source_is_official=False,
            credibility_tier=CredibilityTier.MEDIUM,
            published_at=datetime.fromisoformat(item["published_at"].replace("Z", "+00:00")),
            first_seen_at=datetime.fromisoformat(item["published_at"].replace("Z", "+00:00")),
            title=f"Dengue report from {item['place_name']}",
            locations=(
                LocationForMatching(
                    location_role=LocationRole.PRIMARY,
                    precision=Precision.PLACE,
                    country_code=item["country_code"],
                    admin1=item["admin1"],
                    place_name=item["place_name"],
                    latitude=item["latitude"],
                    longitude=item["longitude"],
                ),
            ),
        )
        for item in payload["reports"]
    )


def test_three_chiang_mai_dengue_reports_become_one_deterministic_cluster() -> None:
    clusters, unclusterable = build_clusters(reports("chiang_mai_three.json"))
    assert len(clusters) == 1
    assert len(clusters[0].signals) == 3
    assert unclusterable == ()


def test_chiang_mai_and_phuket_dengue_stay_separate() -> None:
    clusters, _ = build_clusters(reports("chiang_mai_and_phuket.json"))
    assert len(clusters) == 2


def test_dengue_and_measles_in_one_province_stay_separate() -> None:
    clusters, _ = build_clusters(reports("dengue_and_measles.json"))
    assert len(clusters) == 2


def test_new_linked_follow_up_article_is_due_for_summary_again() -> None:
    first = datetime(2026, 8, 24, 1, 0, tzinfo=UTC)
    assert should_resummarize(
        last_summarized_at=None, latest_observation=None, previous_counts=None
    )
    assert should_resummarize(
        last_summarized_at=first,
        latest_observation=None,
        previous_counts=None,
        unsummarized_articles=1,
    )
    assert not should_resummarize(
        last_summarized_at=first,
        latest_observation=None,
        previous_counts=None,
        unsummarized_articles=0,
    )
