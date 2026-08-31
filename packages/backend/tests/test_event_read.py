from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from episignal_backend.db.types import (
    CredibilityTier,
    EventStatus,
    EventType,
    LocationRole,
    RelationshipType,
    VerificationStatus,
)
from episignal_backend.events.read import query_dashboard_events, query_event_detail


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


def test_dashboard_returns_summarized_events_with_town_then_country_locations() -> None:
    town_event_id = uuid4()
    country_event_id = uuid4()
    now = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
    town_event = SimpleNamespace(
        id=town_event_id,
        public_id="EVT-2026-TOWN",
        headline="Dengue in Chiang Mai",
        summary="Cases are under observation.",
        event_type=EventType.OUTBREAK,
        status=EventStatus.MONITORING,
        country_code="TH",
        first_signal_at=now,
        last_updated_at=now,
        article_count=2,
        last_summarized_at=now,
    )
    country_event = SimpleNamespace(
        id=country_event_id,
        public_id="EVT-2026-COUNTRY",
        headline="Cholera in Nigeria",
        summary="A country-level report is being monitored.",
        event_type=EventType.OUTBREAK,
        status=EventStatus.ONGOING,
        country_code="NG",
        first_signal_at=now,
        last_updated_at=now.replace(hour=1),
        article_count=4,
        last_summarized_at=now,
    )
    town_location = SimpleNamespace(
        id=uuid4(),
        event_id=town_event_id,
        location_role=LocationRole.PRIMARY,
        place_name="Chiang Mai",
        latitude=18.7883,
        longitude=98.9853,
    )
    country_centroid = ("NG", 9.08, 8.68)
    session = FakeSession(
        [
            FakeResult([(country_event, "Cholera"), (town_event, "Dengue")]),
            FakeResult([town_location]),
            FakeResult([country_centroid]),
        ]
    )

    page = query_dashboard_events(session)

    assert page.total == 2
    assert [item.public_id for item in page.items] == [
        "EVT-2026-COUNTRY",
        "EVT-2026-TOWN",
    ]
    assert page.items[0].town is None
    assert page.items[0].map_level == "country"
    assert (page.items[0].latitude, page.items[0].longitude) == (9.08, 8.68)
    assert page.items[1].town == "Chiang Mai"
    assert page.items[1].map_level == "town"
    assert (page.items[1].latitude, page.items[1].longitude) == (18.7883, 98.9853)

    statement = session.executed[0]
    rendered = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "last_summarized_at IS NOT NULL" in rendered
    assert "btrim(events.summary)" in rendered
    assert "ORDER BY events.last_updated_at DESC" in rendered
    assert "published_at" not in rendered
