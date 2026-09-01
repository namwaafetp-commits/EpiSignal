"""End-to-end proof of the relevance stop in the scheduled stage order."""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from episignal_backend.ai.classify import run_classification
from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatResponse,
    ClassifiableSignal,
    ExtractableCluster,
    ExtractableSignal,
    ModelSpec,
)
from episignal_backend.ai.extract import run_extraction
from episignal_backend.ai.ladder import Guards
from episignal_backend.db.types import AiPurpose
from episignal_backend.events.assemble import run_event_assembly
from episignal_backend.ingestion.dedupe import run_dedupe
from episignal_backend.ingestion.documents import ComparableSignal, StubRetrieval
from episignal_backend.ingestion.retrieval import run_retrieval
from episignal_backend.schedule.chains import DAILY_CHAIN
from episignal_backend.schedule.documents import StageName
from episignal_backend.schedule.run import run_chain
from test_event_assemble import FakeAssemblyRepository

NOW = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
SIGNAL_ID = UUID("b3f1c2d4-0000-4000-8000-000000000001")


class DedupeRepository:
    def __init__(self) -> None:
        self.signal = ComparableSignal(
            id=SIGNAL_ID,
            canonical_url="https://example.test/cup",
            title="City wins the cup",
            raw_text="metadata placeholder",
            content_hash="a" * 64,
            first_seen_at=NOW,
        )
        self.normalized = False

    def pending(self, *, limit: int) -> Sequence[ComparableSignal]:
        return (self.signal,) if not self.normalized else ()

    def candidates(
        self, signal: ComparableSignal, *, window_hours: int
    ) -> Sequence[ComparableSignal]:
        return ()

    def primary_of(self, signal_id: UUID) -> UUID:
        return signal_id

    def mark_duplicate(self, signal_id: UUID, primary_id: UUID) -> None:
        raise AssertionError("the fixture has no duplicate")

    def mark_normalized(self, signal_id: UUID) -> None:
        self.normalized = True

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class AiRepository:
    def __init__(self, dedupe: DedupeRepository) -> None:
        self.dedupe = dedupe
        self.relevant: bool | None = None
        self.requests: list[AiRequestRecord] = []

    def models(self) -> Sequence[ModelSpec]:
        return (
            ModelSpec(
                id=uuid4(),
                tier=1,
                model_id="test/classifier",
                label="Test classifier",
                purpose=AiPurpose.CLASSIFICATION,
                prompt_price_per_million=Decimal("0"),
                completion_price_per_million=Decimal("0"),
            ),
        )

    def awaiting_classification(self, *, limit: int) -> Sequence[ClassifiableSignal]:
        if not self.dedupe.normalized:
            return ()
        return (
            ClassifiableSignal(id=SIGNAL_ID, title="City wins the cup", excerpt="A sports report"),
        )

    def awaiting_cluster_extraction(self, *, limit: int) -> Sequence[ExtractableCluster]:
        return ()

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        return ()

    def record_request(self, record: AiRequestRecord) -> None:
        self.requests.append(record)

    def record_classification(self, signal_id: UUID, verdict) -> None:
        self.relevant = verdict.is_public_health_relevant

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class Classifier:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request) -> ChatResponse:
        self.calls += 1
        return ChatResponse(
            content=json.dumps(
                {"results": [{"id": str(SIGNAL_ID), "relevant": False, "confidence": 0.99}]}
            ),
            latency_ms=1,
        )


class RetrievalConnector:
    def __init__(self) -> None:
        self.calls = 0

    def retrieve(self, article, first_seen_at):
        self.calls += 1
        raise AssertionError("irrelevant signals must not be retrieved")


class RetrievalRepository:
    def __init__(self, ai: AiRepository) -> None:
        self.ai = ai

    def gated_awaiting_retrieval(self, *, max_attempts: int, limit: int) -> Sequence[StubRetrieval]:
        return () if self.ai.relevant is False else ()

    def keyword_rules(self):
        return ()

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class ExtractionModel:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request) -> ChatResponse:
        self.calls += 1
        raise AssertionError("irrelevant signals must not be extracted")


def test_daily_order_and_irrelevant_stop_prevent_all_downstream_work() -> None:
    assert DAILY_CHAIN[1:] == (
        StageName.DISCOVER,
        StageName.DEDUPE,
        StageName.CLASSIFY,
        StageName.RETRIEVE,
        StageName.EXTRACT,
        StageName.MATCH,
        StageName.SUMMARIZE,
    )

    dedupe = DedupeRepository()
    ai = AiRepository(dedupe)
    classifier = Classifier()
    retrieval_connector = RetrievalConnector()
    extraction_model = ExtractionModel()
    event_repository = FakeAssemblyRepository()
    summary_calls = 0
    calls: list[StageName] = []

    def discover() -> Mapping[str, int]:
        calls.append(StageName.DISCOVER)
        return {"discovered": 1}

    def deduplicate() -> Mapping[str, int]:
        calls.append(StageName.DEDUPE)
        result = run_dedupe(dedupe, metadata_only=True)
        return {"examined": result.examined}

    def classify() -> Mapping[str, int]:
        calls.append(StageName.CLASSIFY)
        result = run_classification(
            ai,
            classifier,
            guards=Guards(max_requests=5, max_cost_usd=Decimal("1")),
            now=lambda: NOW,
        )
        assert result.examined == 1
        assert result.irrelevant == 1
        assert ai.relevant is False
        return {"irrelevant": result.irrelevant}

    def retrieve() -> Mapping[str, int]:
        calls.append(StageName.RETRIEVE)
        result = run_retrieval(
            RetrievalRepository(ai), retrieval_connector, max_attempts=3, batch_size=10
        )
        return {"retrieved": result.retrieved}

    def extract() -> Mapping[str, int]:
        calls.append(StageName.EXTRACT)
        result = run_extraction(
            ai,
            extraction_model,
            guards=Guards(max_requests=5, max_cost_usd=Decimal("1")),
            now=lambda: NOW,
        )
        return {"extracted": result.extracted}

    def match() -> Mapping[str, int]:
        calls.append(StageName.MATCH)
        result = run_event_assembly(event_repository)
        return {"created": result.events_created}

    def summarize() -> Mapping[str, int]:
        nonlocal summary_calls
        calls.append(StageName.SUMMARIZE)
        if not event_repository.created_events:
            return {}
        summary_calls += 1
        return {}

    run_chain(
        (
            StageName.DISCOVER,
            StageName.DEDUPE,
            StageName.CLASSIFY,
            StageName.RETRIEVE,
            StageName.EXTRACT,
            StageName.MATCH,
            StageName.SUMMARIZE,
        ),
        {
            StageName.DISCOVER: discover,
            StageName.DEDUPE: deduplicate,
            StageName.CLASSIFY: classify,
            StageName.RETRIEVE: retrieve,
            StageName.EXTRACT: extract,
            StageName.MATCH: match,
            StageName.SUMMARIZE: summarize,
        },
    )

    assert calls == [
        StageName.DISCOVER,
        StageName.DEDUPE,
        StageName.CLASSIFY,
        StageName.RETRIEVE,
        StageName.EXTRACT,
        StageName.MATCH,
        StageName.SUMMARIZE,
    ]
    assert retrieval_connector.calls == 0
    assert extraction_model.calls == 0
    assert event_repository.created_events == []
    assert event_repository.recorded_observations == []
    assert summary_calls == 0
