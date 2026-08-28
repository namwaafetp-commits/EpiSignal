from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from episignal_backend.ai.documents import AiRequestRecord, StoredExtraction, Verdict
from episignal_backend.ai.protocol import AiRepository
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.ai.schema import (
    EXTRACTION_SCHEMA_VERSION,
    EXTRACTION_VERSION_KEY,
    Extraction,
)
from episignal_backend.db.types import AiOutcome, AiPurpose, ProcessingStatus, SignalType
from sqlalchemy import Select, Update

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> Any:
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
        return self._results.pop(0) if self._results else FakeResult(None)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def extraction() -> Extraction:
    return Extraction.model_validate(
        {
            "signal_type": "outbreak_report",
            "source_language": "en",
            "title_english": "Cholera outbreak reported in Luanda",
            "brief": [
                {"slot": "what_where", "text": "Cholera in Luanda, Angola.", "reported": True},
                {"slot": "counts", "text": "No case count reported.", "reported": False},
                {"slot": "timing", "text": "No date reported.", "reported": False},
                {"slot": "spread", "text": "No transmission detail reported.", "reported": False},
                {"slot": "reporting", "text": "Reported by local media.", "reported": True},
            ],
            "confidence": 0.9,
        }
    )


def test_it_satisfies_the_storage_boundary() -> None:
    assert isinstance(SqlAlchemyAiRepository(FakeSession()), AiRepository)


def test_only_normalized_signals_are_offered_for_classification() -> None:
    session = FakeSession([FakeResult([])])

    SqlAlchemyAiRepository(session).awaiting_classification(limit=10)

    statement = session.executed[0]
    assert isinstance(statement, Select)
    rendered = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert f"'{ProcessingStatus.NORMALIZED.value}'" in rendered
    assert f"'{ProcessingStatus.DUPLICATE.value}'" not in rendered
    assert f"'{ProcessingStatus.NEEDS_REVIEW.value}'" not in rendered
    assert "raw_text IS NOT NULL" in rendered


def test_only_relevant_classified_signals_are_offered_for_extraction() -> None:
    session = FakeSession([FakeResult([])])

    SqlAlchemyAiRepository(session).awaiting_extraction(limit=10)

    rendered = str(session.executed[0].compile(compile_kwargs={"literal_binds": True}))
    assert ProcessingStatus.CLASSIFIED.value in rendered
    assert "public_health_relevant" in rendered


def test_a_verdict_writes_the_relevance_and_the_classified_status() -> None:
    session = FakeSession()

    SqlAlchemyAiRepository(session).record_classification(
        uuid4(),
        Verdict(
            is_public_health_relevant=False,
            signal_type=SignalType.UNKNOWN,
            relevance=0.04,
            model_id="vendor/model:free",
            decided_at=NOW,
        ),
    )

    statement = session.executed[0]
    assert isinstance(statement, Update)
    params = statement.compile().params
    assert ProcessingStatus.CLASSIFIED in params.values()


def test_an_accepted_extraction_writes_the_json_the_model_and_the_time() -> None:
    session = FakeSession()

    SqlAlchemyAiRepository(session).record_extraction(
        uuid4(),
        StoredExtraction(
            extraction=extraction(),
            disease_id=None,
            model_id="vendor/model:free",
            processed_at=NOW,
        ),
    )

    statement = session.executed[0]
    assert isinstance(statement, Update)
    params = statement.compile().params
    assert ProcessingStatus.EXTRACTED in params.values()


def test_a_cost_row_is_added_for_every_request() -> None:
    session = FakeSession()

    SqlAlchemyAiRepository(session).record_request(
        AiRequestRecord(
            ai_model_id=uuid4(),
            model_id="vendor/model:free",
            tier=1,
            purpose=AiPurpose.CLASSIFICATION,
            signal_id=None,
            batch_size=20,
            prompt_tokens=900,
            completion_tokens=120,
            latency_ms=740,
            http_status=200,
            outcome=AiOutcome.ACCEPTED,
            rejection_reason=None,
            prompt_price_per_million=Decimal("0"),
            completion_price_per_million=Decimal("0"),
            cost_usd=Decimal("0"),
            requested_at=NOW,
        )
    )

    assert len(session.added) == 1
    assert session.added[0].batch_size == 20


def test_a_disease_is_resolved_case_insensitively_or_not_at_all() -> None:
    identifier = uuid4()
    session = FakeSession([FakeResult(identifier), FakeResult(None)])
    repository = SqlAlchemyAiRepository(session)

    assert repository.resolve_disease("cholera") == identifier
    assert repository.resolve_disease("a disease nobody seeded") is None


def test_an_accepted_extraction_stores_the_brief_as_the_signal_summary() -> None:
    session = FakeSession()

    SqlAlchemyAiRepository(session).record_extraction(
        uuid4(),
        StoredExtraction(
            extraction=extraction(),
            disease_id=None,
            model_id="vendor/model:free",
            processed_at=NOW,
        ),
    )

    params = session.executed[0].compile().params
    summary = next(value for value in params.values() if isinstance(value, str) and "\n" in value)
    assert summary.splitlines() == [
        "Cholera in Luanda, Angola.",
        "No case count reported.",
        "No date reported.",
        "No transmission detail reported.",
        "Reported by local media.",
    ]


def test_an_accepted_extraction_stamps_the_schema_version() -> None:
    session = FakeSession()

    SqlAlchemyAiRepository(session).record_extraction(
        uuid4(),
        StoredExtraction(
            extraction=extraction(),
            disease_id=None,
            model_id="vendor/model:free",
            processed_at=NOW,
        ),
    )

    params = session.executed[0].compile().params
    stored = next(value for value in params.values() if isinstance(value, dict))
    assert stored[EXTRACTION_VERSION_KEY] == EXTRACTION_SCHEMA_VERSION
    assert stored["brief"][0]["slot"] == "what_where"


def test_the_backfill_selects_only_extractions_below_the_current_version() -> None:
    session = FakeSession([FakeResult([])])

    SqlAlchemyAiRepository(session).awaiting_backfill(limit=10)

    statement = str(session.executed[0])
    assert "processing_status IN" in statement
    assert "ai_extraction IS NOT NULL" in statement
    assert "raw_text IS NOT NULL" in statement


def test_the_backfill_never_selects_a_signal_awaiting_a_human() -> None:
    session = FakeSession([FakeResult([])])

    SqlAlchemyAiRepository(session).awaiting_backfill(limit=10)

    compiled = session.executed[0].compile()
    selected = [value for value in compiled.params.values() if isinstance(value, str)]
    assert ProcessingStatus.NEEDS_REVIEW.value not in selected
    assert ProcessingStatus.NORMALIZED.value not in selected
