"""Synthetic acceptance fixture routed through the real pure pipeline seams.

The classifier is a fake model boundary. Deduplication, clustering, matching,
event finalization, and observation recording are the production domain
functions used by the scheduled pipeline.
"""

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from episignal_backend.db.types import CredibilityTier, LocationRole, Precision
from episignal_backend.events.assemble import run_event_assembly
from episignal_backend.events.documents import LocationForMatching, SignalForMatching
from episignal_backend.ingestion.dedupe import DedupeThresholds, run_dedupe
from episignal_backend.ingestion.documents import ComparableSignal
from test_event_assemble import FakeAssemblyRepository

FIXTURE = Path(__file__).parent / "fixtures" / "lean_mvp" / "30_candidates.json"


class FakeClassifier:
    """Scripted model boundary: only the model answer comes from fixture data."""

    def __init__(self, articles: list[dict]) -> None:
        self._answers = {article["id"]: article["relevant"] for article in articles}
        self.calls = 0

    def classify(self, article: dict) -> bool:
        self.calls += 1
        return self._answers[article["id"]]


class InMemoryDedupeRepository:
    def __init__(self, signals: list[ComparableSignal]) -> None:
        self._signals = tuple(signals)
        self.duplicates: list[tuple[UUID, UUID]] = []
        self.normalized: list[UUID] = []

    def pending(self, *, limit: int) -> tuple[ComparableSignal, ...]:
        return self._signals[:limit]

    def candidates(
        self, signal: ComparableSignal, *, window_hours: int
    ) -> tuple[ComparableSignal, ...]:
        return tuple(candidate for candidate in self._signals if candidate.id != signal.id)

    def primary_of(self, signal_id: UUID) -> UUID:
        for duplicate_id, primary_id in self.duplicates:
            if duplicate_id == signal_id:
                return self.primary_of(primary_id)
        return signal_id

    def mark_duplicate(self, signal_id: UUID, primary_id: UUID) -> None:
        self.duplicates.append((signal_id, primary_id))

    def mark_normalized(self, signal_id: UUID) -> None:
        self.normalized.append(signal_id)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def _timestamp(article: dict) -> datetime:
    return datetime.fromisoformat(article["published_at"].replace("Z", "+00:00"))


def _signal(article: dict) -> ComparableSignal:
    body = article["snippet"]
    return ComparableSignal(
        id=uuid5(NAMESPACE_URL, f"fixture:signal:{article['id']}"),
        canonical_url=article["url"],
        title=article["title"],
        raw_text=body,
        content_hash=sha256(f"{article['id']}:{body}".encode()).hexdigest(),
        first_seen_at=_timestamp(article),
        published_at=_timestamp(article),
    )


def _country_for(place: str) -> str:
    return {
        "Chiang Mai": "TH",
        "Phuket": "TH",
        "Bangkok": "TH",
        "Lusaka": "ZM",
        "Lampung": "ID",
        "Hanoi": "VN",
        "Piraeus": "GR",
        "Sao Paulo": "BR",
        "Yunnan": "CN",
        "Sylhet": "BD",
    }[place]


def _matching_signal(article: dict) -> SignalForMatching:
    place = article["place"]
    coordinates = {
        "Chiang Mai": (18.79, 98.98),
        "Phuket": (7.88, 98.39),
        "Bangkok": (13.76, 100.50),
        "Lusaka": (-15.39, 28.32),
        "Lampung": (-5.43, 105.26),
        "Hanoi": (21.03, 105.85),
        "Piraeus": (37.94, 23.65),
        "Sao Paulo": (-23.55, -46.63),
        "Yunnan": (25.04, 102.71),
        "Sylhet": (24.89, 91.87),
    }[place]
    location = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code=_country_for(place),
        admin1=place,
        place_name=place,
        latitude=coordinates[0],
        longitude=coordinates[1],
    )
    return SignalForMatching(
        signal_id=uuid5(NAMESPACE_URL, f"fixture:signal:{article['id']}"),
        disease_id=uuid5(NAMESPACE_URL, f"fixture:disease:{article['disease']}"),
        source_id=uuid5(NAMESPACE_URL, f"fixture:source:{article['id']}"),
        source_is_official=True,
        credibility_tier=CredibilityTier.OFFICIAL,
        published_at=_timestamp(article),
        first_seen_at=_timestamp(article),
        title=article["title"],
        locations=(location,),
    )


def test_the_lean_mvp_fixture_runs_real_dedupe_matching_and_observations() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    articles: list[dict] = payload["articles"]
    assert len(articles) == 30

    dedupe_repository = InMemoryDedupeRepository([_signal(article) for article in articles])
    dedupe = run_dedupe(
        dedupe_repository,
        thresholds=DedupeThresholds(near_exact_title=92.0),
        window_hours=48,
    )

    assert dedupe.examined == 30
    assert dedupe.duplicates == 5
    assert dedupe.primaries == 25
    representatives_by_id = {
        article["id"]: article
        for article in articles
        if uuid5(NAMESPACE_URL, f"fixture:signal:{article['id']}") in dedupe_repository.normalized
    }
    assert len(representatives_by_id) == 25

    classifier = FakeClassifier(articles)
    relevant = [
        article for article in representatives_by_id.values() if classifier.classify(article)
    ]
    assert classifier.calls == 25
    assert len(relevant) == 15

    candidates_by_disease: dict[UUID, list] = {}
    events_created = 0
    signals_attached = 0
    observations = 0
    for article in sorted(relevant, key=_timestamp):
        signal = _matching_signal(article)
        disease_id = signal.disease_id
        assert disease_id is not None
        candidates = candidates_by_disease.setdefault(disease_id, [])
        repository = FakeAssemblyRepository([signal], {disease_id: list(candidates)})
        summary = run_event_assembly(
            repository,
            now=signal.published_at,
            match_threshold=0.75,
            review_threshold=0.55,
        )
        events_created += summary.events_created
        signals_attached += summary.signals_attached
        observations += len(repository.recorded_observations)
        candidates.extend(repository.created_events)
        for index, candidate in enumerate(candidates):
            if any(event_id == candidate.event_id for event_id, *_ in repository.attached_signals):
                candidates[index] = candidate.model_copy(
                    update={"last_updated_at": signal.published_at}
                )

    assert events_created == 11
    assert signals_attached == 15
    assert observations == 15
