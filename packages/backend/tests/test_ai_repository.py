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


class FakeScalarResult:
    """Stands in for SQLAlchemy's ScalarResult: iterable, and answers `all()`."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def __iter__(self) -> Any:
        return iter(self._value or ())

    def all(self) -> list[Any]:
        return list(self._value or ())


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> FakeScalarResult:
        return FakeScalarResult(self._value)

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
                {
                    "slot": "reporting",
                    "text": "Reported by Angola's health ministry.",
                    "reported": True,
                },
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
        "Reported by Angola's health ministry.",
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


class FakeSignalModel:
    def __init__(
        self,
        *,
        id: Any = None,
        title: str = "Cholera in Luanda",
        raw_text: str | None = "50 cases of cholera reported in Luanda.",
        content_hash: str | None = None,
    ) -> None:
        self.id = id or uuid4()
        self.title = title
        self.raw_text = raw_text
        if content_hash is not None:
            self.content_hash = content_hash
        else:
            from episignal_backend.ingestion.fingerprint import content_hash as compute_hash

            self.content_hash = compute_hash(title, raw_text or "")


def test_awaiting_classification_scans_past_mismatched_content_hash_honoring_limit(
    caplog: Any,
) -> None:
    corrupted = FakeSignalModel(
        title="Pennsylvania measles",
        raw_text="Luanda cholera",
        content_hash="bad_hash_00000000000000000000000000000000000000000000000000000000",
    )
    valid1 = FakeSignalModel(title="Valid title 1", raw_text="Valid body 1")
    valid2 = FakeSignalModel(title="Valid title 2", raw_text="Valid body 2")
    session = FakeSession([FakeResult([corrupted, valid1, valid2])])

    with caplog.at_level("WARNING"):
        results = SqlAlchemyAiRepository(session).awaiting_classification(limit=2)

    assert len(results) == 2
    assert results[0].id == valid1.id
    assert results[1].id == valid2.id
    assert str(corrupted.id) in caplog.text
    assert "failed content hash integrity" in caplog.text


def test_awaiting_extraction_scans_past_mismatched_content_hash_honoring_limit(
    caplog: Any,
) -> None:
    corrupted = FakeSignalModel(
        title="Pennsylvania measles",
        raw_text="Luanda cholera",
        content_hash="bad_hash_00000000000000000000000000000000000000000000000000000000",
    )
    valid1 = FakeSignalModel(title="Valid title 1", raw_text="Valid body 1")
    valid2 = FakeSignalModel(title="Valid title 2", raw_text="Valid body 2")
    session = FakeSession([FakeResult([corrupted, valid1, valid2])])

    with caplog.at_level("WARNING"):
        results = SqlAlchemyAiRepository(session).awaiting_extraction(limit=2)

    assert len(results) == 2
    assert results[0].id == valid1.id
    assert results[1].id == valid2.id
    assert str(corrupted.id) in caplog.text
    assert "failed content hash integrity" in caplog.text


def test_awaiting_backfill_scans_past_mismatched_content_hash_honoring_limit(
    caplog: Any,
) -> None:
    corrupted = FakeSignalModel(
        title="Pennsylvania measles",
        raw_text="Luanda cholera",
        content_hash="bad_hash_00000000000000000000000000000000000000000000000000000000",
    )
    valid1 = FakeSignalModel(title="Valid title 1", raw_text="Valid body 1")
    valid2 = FakeSignalModel(title="Valid title 2", raw_text="Valid body 2")
    session = FakeSession([FakeResult([corrupted, valid1, valid2])])

    with caplog.at_level("WARNING"):
        results = SqlAlchemyAiRepository(session).awaiting_backfill(limit=2)

    assert len(results) == 2
    assert results[0].id == valid1.id
    assert results[1].id == valid2.id
    assert str(corrupted.id) in caplog.text
    assert "failed content hash integrity" in caplog.text


def test_awaiting_classification_does_not_stall_when_corrupted_row_persists_at_head() -> None:
    corrupted = FakeSignalModel(
        title="Pennsylvania measles",
        raw_text="Luanda cholera",
        content_hash="bad_hash_00000000000000000000000000000000000000000000000000000000",
    )
    valid1 = FakeSignalModel(title="Valid 1", raw_text="Body 1")
    valid2 = FakeSignalModel(title="Valid 2", raw_text="Body 2")
    valid3 = FakeSignalModel(title="Valid 3", raw_text="Body 3")
    valid4 = FakeSignalModel(title="Valid 4", raw_text="Body 4")

    # Batch 1: corrupt row at head followed by valid1, valid2, valid3
    session1 = FakeSession([FakeResult([corrupted, valid1, valid2, valid3])])
    batch1 = SqlAlchemyAiRepository(session1).awaiting_classification(limit=2)
    assert len(batch1) == 2
    assert batch1[0].id == valid1.id
    assert batch1[1].id == valid2.id

    # Batch 2: valid1 and valid2 have been classified, so their status has advanced.
    # The next query still sees the corrupted row at the head, then valid3 and valid4.
    session2 = FakeSession([FakeResult([corrupted, valid3, valid4])])
    batch2 = SqlAlchemyAiRepository(session2).awaiting_classification(limit=2)
    assert len(batch2) == 2
    assert batch2[0].id == valid3.id
    assert batch2[1].id == valid4.id
