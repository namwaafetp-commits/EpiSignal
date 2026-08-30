import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from episignal_backend.ai.embeddings import cosine, normalize
from episignal_backend.db.types import CredibilityTier, LocationRole, Precision
from episignal_backend.events.documents import (
    CandidateEvent,
    LocationForMatching,
    MatchAction,
    SignalForMatching,
    StoryCluster,
)
from episignal_backend.events.match import decide

FIXTURES = Path(__file__).parent / "fixtures" / "calibration"


@dataclass(frozen=True)
class CalibrationOutcome:
    events: int
    articles_attached: int
    resummarized: bool


def _reports(name: str) -> list[SignalForMatching]:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    reports: list[SignalForMatching] = []
    for item in payload["reports"]:
        location = LocationForMatching(
            location_role=LocationRole.PRIMARY,
            precision=Precision.PLACE,
            country_code=item["country_code"],
            admin1=item["admin1"],
            place_name=item["place_name"],
            latitude=item["latitude"],
            longitude=item["longitude"],
        )
        reports.append(
            SignalForMatching(
                signal_id=UUID(item["signal_id"]),
                disease_id=UUID(item["disease_id"]),
                source_id=uuid4(),
                source_is_official=False,
                credibility_tier=CredibilityTier.MEDIUM,
                published_at=item["published_at"],
                first_seen_at=item["published_at"],
                locations=(location,),
                embedding=tuple(normalize(item["embedding"])),
            )
        )
    return reports


def assemble(name: str) -> CalibrationOutcome:
    events: list[CandidateEvent] = []
    attached = 0

    for signal in _reports(name):
        cluster = StoryCluster(signals=(signal,))
        assert signal.published_at is not None
        candidates = [
            event
            for event in events
            if event.disease_id == signal.disease_id
            and event.last_updated_at >= signal.published_at - timedelta(days=7)
        ]

        def similarity_for(
            story: StoryCluster,
            candidate: CandidateEvent,
        ) -> float | None:
            left = story.representative_embedding
            right = candidate.representative_embedding
            return cosine(left, right) if left is not None and right is not None else None

        decision = decide(
            cluster,
            candidates,
            threshold=0.80,
            similarity_for=similarity_for,
        )
        if decision.action is MatchAction.ATTACH:
            assert decision.event_id is not None
            index = next(i for i, event in enumerate(events) if event.event_id == decision.event_id)
            events[index] = events[index].model_copy(
                update={"last_updated_at": signal.published_at}
            )
        elif decision.action is MatchAction.CREATE:
            location = cluster.representative_location
            events.append(
                CandidateEvent(
                    event_id=uuid4(),
                    disease_id=signal.disease_id,
                    locations=(location,) if location is not None else (),
                    first_signal_at=signal.published_at,
                    last_updated_at=signal.published_at,
                    representative_embedding=signal.embedding,
                )
            )
        else:
            raise AssertionError("calibration fixture produced an ambiguous match")
        attached += 1

    return CalibrationOutcome(
        events=len(events),
        articles_attached=attached,
        resummarized=False,
    )


def events_from(name: str) -> int:
    return assemble(name).events


def test_three_chiang_mai_dengue_reports_become_one_event() -> None:
    assert events_from("chiang_mai_three.json") == 1


def test_chiang_mai_and_phuket_dengue_stay_separate() -> None:
    assert events_from("chiang_mai_and_phuket.json") == 2


def test_dengue_and_measles_in_one_province_stay_separate() -> None:
    assert events_from("dengue_and_measles.json") == 2


@pytest.mark.xfail(reason="resummarization lands in Task 23", strict=True)
def test_a_wednesday_follow_up_joins_mondays_event_and_updates_it() -> None:
    outcome = assemble("monday_then_wednesday.json")

    assert outcome.events == 1
    assert outcome.articles_attached == 2
    assert outcome.resummarized is True
