import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from episignal_backend.ai.documents import ChatResponse, ModelSpec
from episignal_backend.ai.embeddings import cosine, normalize
from episignal_backend.db.types import CredibilityTier, LocationRole, Precision
from episignal_backend.events.documents import (
    CandidateEvent,
    EventForSummary,
    LocationForMatching,
    MatchAction,
    SignalForMatching,
    StoryCluster,
    SummarySource,
)
from episignal_backend.events.match import decide
from episignal_backend.events.summarize import (
    SummaryOutcome,
    run_summary,
    should_resummarize,
)

FIXTURES = Path(__file__).parent / "fixtures" / "calibration"


@dataclass(frozen=True)
class CalibrationOutcome:
    events: int
    articles_attached: int
    resummarized: bool
    observations: int = 0
    summary_updates: int = 0


class FakeSummaryModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request) -> ChatResponse:
        self.calls += 1
        return ChatResponse(
            content=json.dumps(
                {
                    "headline": "Dengue Outbreak: Chiang Mai — Increasing",
                    "trajectory": "Increasing",
                    "snapshot": [
                        "The reported case count changed.",
                        "Chiang Mai",
                    ],
                    "key_driver": "Not yet established.",
                    "response": "No specific response reported.",
                    "risk": "Insufficient evidence for a broader risk assessment.",
                }
            ),
            latency_ms=5,
        )


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
                title=f"Dengue report from {item['place_name']}",
                locations=(location,),
                embedding=tuple(normalize(item["embedding"])),
            )
        )
    return reports


def _counts(report: SignalForMatching, payload: dict) -> dict[str, object]:
    published = report.published_at
    return {
        "data_as_of": published.date().isoformat() if published is not None else None,
        "confirmed_cases": payload.get("total_cases"),
        "total_cases": payload.get("total_cases"),
        "deaths": None,
        "new_cases": None,
        "new_deaths": None,
    }


def _summary_spec() -> ModelSpec:
    from decimal import Decimal

    return ModelSpec(
        id=uuid4(),
        tier=1,
        model_id="fake-summary-model",
        label="Fake summary model",
        prompt_price_per_million=Decimal("0.01"),
        completion_price_per_million=Decimal("0.01"),
    )


def assemble(name: str) -> CalibrationOutcome:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    reports = _reports(name)
    report_payload = {UUID(item["signal_id"]): item for item in payload["reports"]}
    events: list[CandidateEvent] = []
    observations_by_event: dict[UUID, list[SignalForMatching]] = {}
    summary_counts: dict[UUID, dict[str, object] | None] = {}
    summarized_at: dict[UUID, datetime | None] = {}
    summary_updates = 0
    attached = 0
    summary_model = FakeSummaryModel()
    summary_spec = _summary_spec()

    for signal in reports:
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
            threshold=0.75,
            review_threshold=0.55,
            similarity_for=similarity_for,
        )
        event_id: UUID
        if decision.action is MatchAction.ATTACH:
            assert decision.event_id is not None
            event_id = decision.event_id
            index = next(i for i, event in enumerate(events) if event.event_id == event_id)
            events[index] = events[index].model_copy(
                update={"last_updated_at": signal.published_at}
            )
        elif decision.action is MatchAction.CREATE:
            location = cluster.representative_location
            created = CandidateEvent(
                event_id=uuid4(),
                disease_id=signal.disease_id,
                locations=(location,) if location is not None else (),
                first_signal_at=signal.published_at,
                last_updated_at=signal.published_at,
                representative_embedding=signal.embedding,
            )
            events.append(created)
            event_id = created.event_id
        else:
            raise AssertionError("calibration fixture produced an ambiguous match")

        attached += 1
        history = observations_by_event.setdefault(event_id, [])
        history.append(signal)

        if name != "monday_then_wednesday.json":
            continue
        latest_counts = _counts(signal, report_payload[signal.signal_id])
        due = should_resummarize(
            last_summarized_at=summarized_at.get(event_id),
            latest_observation=latest_counts,
            previous_counts=summary_counts.get(event_id),
            unsummarized_articles=1,
            now=signal.published_at,
            max_age_hours=72,
            new_article_count=3,
        )
        if not due:
            continue
        sources = tuple(
            SummarySource(
                signal_id=report.signal_id,
                title=report.title,
                source_name="Calibration health office",
                is_official=True,
                published_at=report.published_at,
            )
            for report in history
        )
        summary_result = run_summary(
            summary_model,
            summary_spec,
            event=EventForSummary(
                event_id=event_id,
                public_id=f"CAL-{event_id.hex[:8]}",
                disease="dengue",
                location="Chiang Mai",
                previous_counts=summary_counts.get(event_id),
                latest_observation=latest_counts,
                unsummarized_articles=1,
                last_summarized_at=summarized_at.get(event_id),
            ),
            sources=sources,
        )
        assert summary_result.outcome is SummaryOutcome.ACCEPTED
        summary_counts[event_id] = latest_counts
        summarized_at[event_id] = signal.published_at
        summary_updates += 1

    return CalibrationOutcome(
        events=len(events),
        articles_attached=attached,
        resummarized=summary_updates > 1,
        observations=sum(len(history) for history in observations_by_event.values()),
        summary_updates=summary_updates,
    )


def events_from(name: str) -> int:
    return assemble(name).events


def test_three_chiang_mai_dengue_reports_become_one_event() -> None:
    assert events_from("chiang_mai_three.json") == 1


def test_chiang_mai_and_phuket_dengue_stay_separate() -> None:
    assert events_from("chiang_mai_and_phuket.json") == 2


def test_dengue_and_measles_in_one_province_stay_separate() -> None:
    assert events_from("dengue_and_measles.json") == 2


def test_a_wednesday_follow_up_joins_mondays_event_and_updates_it() -> None:
    outcome = assemble("monday_then_wednesday.json")

    assert outcome.events == 1
    assert outcome.articles_attached == 2
    assert outcome.observations == 2
    assert outcome.summary_updates == 2
    assert outcome.resummarized is True
