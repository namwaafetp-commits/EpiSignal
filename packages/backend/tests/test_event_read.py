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
from episignal_backend.events.read import (
    normalize_summary_snapshot,
    query_dashboard_events,
    query_event_detail,
)


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


def test_event_detail_normalizes_legacy_snapshot_objects_to_fact_lists() -> None:
    event_id = uuid4()
    now = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
    event = SimpleNamespace(
        id=event_id,
        public_id="EVT-2026-LEGACY",
        headline="Dengue outbreak",
        summary="Legacy summary",
        event_type=EventType.OUTBREAK,
        status=EventStatus.MONITORING,
        verification_status=VerificationStatus.SIGNAL,
        country_code="TH",
        admin1=None,
        admin2=None,
        first_signal_at=now,
        last_updated_at=now,
        article_count=1,
        last_summarized_at=now,
        early_signal_score=None,
        evidence_score=None,
    )
    legacy = SimpleNamespace(
        version=1,
        headline="Dengue outbreak",
        summary="Legacy summary",
        trajectory=None,
        snapshot={
            "cases": "42 confirmed cases",
            "deaths": None,
            "cfr": "4.2% CFR",
            "geographic_extent": "Chiang Mai",
        },
        key_driver=None,
        response=None,
        risk=None,
        model_id="old-model",
        created_at=now,
    )
    session = FakeSession(
        [
            FakeResult((event, "Dengue")),
            FakeResult([]),
            FakeResult([]),
            FakeResult([legacy]),
        ]
    )

    detail = query_event_detail(session, public_id=event.public_id)

    assert detail is not None
    assert detail.summaries[0].snapshot == (
        "42 confirmed cases",
        "4.2% CFR",
        "Chiang Mai",
    )


def test_legacy_snapshot_combines_deaths_and_cfr_without_exceeding_three_facts() -> None:
    assert normalize_summary_snapshot(
        {
            "cases": "412 cases",
            "deaths": "18 deaths",
            "cfr": "CFR 4.4%",
            "geographic_extent": "4 counties",
        }
    ) == ("412 cases", "18 deaths / CFR 4.4%", "4 counties")


def test_legacy_snapshot_preserves_deaths_when_cfr_is_missing() -> None:
    assert normalize_summary_snapshot(
        {"cases": "27 illnesses", "deaths": "2 deaths", "cfr": None}
    ) == ("27 illnesses", "2 deaths")


def test_dashboard_resolves_admin1_then_country_and_leaves_missing_country_unmapped() -> None:
    admin1_event_id = uuid4()
    country_event_id = uuid4()
    unmapped_event_id = uuid4()
    now = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
    admin1_event = SimpleNamespace(
        id=admin1_event_id,
        public_id="EVT-2026-ADMIN1",
        headline="Dengue in Chiang Mai",
        summary="Cases are under observation.",
        event_type=EventType.OUTBREAK,
        status=EventStatus.MONITORING,
        country_code="TH",
        admin1="CM",
        first_signal_at=now,
        last_updated_at=now.replace(hour=2),
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
        admin1=None,
        first_signal_at=now,
        last_updated_at=now.replace(hour=1),
        article_count=4,
        last_summarized_at=now,
    )
    unmapped_event = SimpleNamespace(
        id=unmapped_event_id,
        public_id="EVT-2026-UNMAPPED",
        headline="Influenza in Unknown Province",
        summary="A report without a gazetteer match.",
        event_type=EventType.OUTBREAK,
        status=EventStatus.MONITORING,
        country_code="ZZ",
        admin1="Unknown Province",
        first_signal_at=now,
        last_updated_at=now,
        article_count=1,
        last_summarized_at=now,
    )
    admin1_centroid = ("TH", "CM", "Chiang Mai", "chiang mai", "chiang mai", 18.7883, 98.9853)
    country_centroid = ("NG", 9.08, 8.68)
    session = FakeSession(
        [
            FakeResult(
                [
                    (admin1_event, "Dengue"),
                    (country_event, "Cholera"),
                    (unmapped_event, "Influenza"),
                ]
            ),
            FakeResult([admin1_centroid]),
            FakeResult([country_centroid]),
        ]
    )

    page = query_dashboard_events(session)

    assert page.total == 3
    assert [item.public_id for item in page.items] == [
        "EVT-2026-ADMIN1",
        "EVT-2026-COUNTRY",
        "EVT-2026-UNMAPPED",
    ]
    assert page.items[0].admin1 == "Chiang Mai"
    assert page.items[0].map_level == "admin1"
    assert (page.items[0].latitude, page.items[0].longitude) == (18.7883, 98.9853)
    assert page.items[1].admin1 is None
    assert page.items[1].map_level == "country"
    assert (page.items[1].latitude, page.items[1].longitude) == (9.08, 8.68)
    assert page.items[2].admin1 == "Unknown Province"
    assert page.items[2].map_level is None
    assert (page.items[2].latitude, page.items[2].longitude) == (None, None)

    statement = session.executed[0]
    rendered = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "last_summarized_at IS NOT NULL" in rendered
    assert "btrim(events.summary)" in rendered
    assert "ORDER BY events.last_updated_at DESC" in rendered
    assert "published_at" not in rendered
    assert not any("event_locations" in str(statement) for statement in session.executed)
