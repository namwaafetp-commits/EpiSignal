from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from episignal_backend.db.types import (
    CredibilityTier,
    LocationRole,
    Precision,
    SignalType,
)
from episignal_backend.events.protocol import EventRepository
from episignal_backend.events.repository import SqlAlchemyEventRepository


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> Any:
        return self._value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = results or []
        self.executed: list[Any] = []
        self.added: list[Any] = []

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return self._results.pop(0) if self._results else FakeResult([])

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class FakeSignal:
    def __init__(
        self,
        signal_id,
        disease_id,
        source_id,
        published_at,
        first_seen_at,
        is_official,
        credibility_tier,
        extraction=None,
    ) -> None:
        self.id = signal_id
        self.disease_id = disease_id
        self.source_id = source_id
        self.published_at = published_at
        self.first_seen_at = first_seen_at
        self.is_official = is_official
        self.credibility_tier = credibility_tier
        self.ai_extraction = extraction


class FakeLocation:
    def __init__(
        self,
        signal_id,
        role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        admin2="Beni",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    ) -> None:
        self.signal_id = signal_id
        self.location_role = role
        self.precision = precision
        self.country_code = country_code
        self.admin1 = admin1
        self.admin2 = admin2
        self.place_name = place_name
        self.latitude = latitude
        self.longitude = longitude


def test_it_satisfies_the_event_repository_boundary() -> None:
    repo = SqlAlchemyEventRepository(FakeSession())
    assert isinstance(repo, EventRepository)


def test_signals_to_match_queries_geocoded_signals_and_maps_locations() -> None:
    sig_id = uuid4()
    disease_id = uuid4()
    src_id = uuid4()
    now = datetime.now(UTC)

    fake_sig = FakeSignal(
        signal_id=sig_id,
        disease_id=disease_id,
        source_id=src_id,
        published_at=now,
        first_seen_at=now,
        is_official=True,
        credibility_tier=CredibilityTier.OFFICIAL,
        extraction={
            "signal_type": "outbreak_report",
            "summary": "Outbreak in Beni",
            "confidence": 0.95,
        },
    )
    fake_loc = FakeLocation(signal_id=sig_id)

    # First execute is signals select, second execute is locations select
    session = FakeSession(
        [
            FakeResult([(fake_sig, True, CredibilityTier.OFFICIAL)]),
            FakeResult([fake_loc]),
        ]
    )

    repo = SqlAlchemyEventRepository(session)
    signals = repo.signals_to_match(limit=10, stale=False)

    assert len(signals) == 1
    sig = signals[0]
    assert sig.signal_id == sig_id
    assert sig.disease_id == disease_id
    assert sig.source_is_official is True
    assert sig.credibility_tier == CredibilityTier.OFFICIAL
    assert len(sig.locations) == 1
    assert sig.locations[0].place_name == "Beni"
    assert sig.extraction is not None
    assert sig.extraction.signal_type == SignalType.OUTBREAK_REPORT

    # Assert executed statement checked processing_status
    stmt_str = str(session.executed[0])
    assert "processing_status" in stmt_str
