from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from episignal_backend.db.types import (
    CredibilityTier,
    EventStatus,
    EventType,
    RelationshipType,
    VerificationStatus,
)
from episignal_backend.events.read import query_event_detail


class FakeResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def first(self) -> Any:
        return self.value[0] if isinstance(self.value, list) and self.value else self.value

    def all(self) -> Any:
        return self.value or []

    def scalars(self) -> "FakeResult":
        return self


class FakeSession:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = results
        self.executed: list[Any] = []

    def execute(self, statement: Any) -> FakeResult:
        self.executed.append(statement)
        return self.results.pop(0)


def test_event_detail_loads_sources_through_event_signal_join() -> None:
    event_id = uuid4()
    signal_id = uuid4()
    now = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
    event = SimpleNamespace(
        id=event_id,
        public_id="EVT-2026-00042",
        headline=None,
        summary=None,
        event_type=EventType.OUTBREAK,
        status=EventStatus.MONITORING,
        verification_status=VerificationStatus.SIGNAL,
        country_code=None,
        admin1=None,
        admin2=None,
        first_signal_at=now,
        last_updated_at=now,
        article_count=1,
        last_summarized_at=None,
        early_signal_score=None,
        evidence_score=None,
    )
    session = FakeSession(
        [
            FakeResult((event, "Dengue")),
            FakeResult(
                [
                    (
                        signal_id,
                        "Public Health Office",
                        True,
                        CredibilityTier.OFFICIAL,
                        "Dengue cases rise",
                        "https://health.example/report/1",
                        now,
                        now,
                        RelationshipType.INITIAL_REPORT,
                        True,
                    )
                ]
            ),
            FakeResult([]),
            FakeResult([]),
        ]
    )

    detail = query_event_detail(session, public_id=event.public_id)

    assert detail is not None
    assert len(detail.sources) == 1
    assert detail.sources[0].signal_id == signal_id
    assert detail.sources[0].source_name == "Public Health Office"
