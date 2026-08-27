from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from episignal_backend.ingestion.documents import ComparableSignal
from episignal_backend.ingestion.protocol import DedupeRepository
from episignal_backend.ingestion.repository import SqlAlchemyDedupeRepository
from episignal_backend.models import Signal

FIRST = datetime(2026, 8, 25, 19, 0, tzinfo=UTC)


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

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return self._results.pop(0) if self._results else FakeResult(None)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def row(**overrides: Any) -> Signal:
    signal = Signal(
        source_id=uuid4(),
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        title="Measles deaths confirmed",
        raw_text="Two people died.",
        retrieved_at=FIRST,
        first_seen_at=FIRST,
        content_hash="a" * 64,
    )
    signal.id = uuid4()
    for name, value in overrides.items():
        setattr(signal, name, value)
    return signal


def test_pending_returns_comparable_signals() -> None:
    stored = row()
    session = FakeSession([FakeResult([stored])])
    repository = SqlAlchemyDedupeRepository(session)

    pending = repository.pending(limit=10)

    assert len(pending) == 1
    assert isinstance(pending[0], ComparableSignal)
    assert pending[0].id == stored.id
    assert pending[0].content_hash == "a" * 64


def test_marking_a_duplicate_issues_one_update() -> None:
    session = FakeSession()
    repository = SqlAlchemyDedupeRepository(session)

    repository.mark_duplicate(uuid4(), uuid4())

    assert len(session.executed) == 1


def test_marking_normalized_issues_one_update() -> None:
    session = FakeSession()
    repository = SqlAlchemyDedupeRepository(session)

    repository.mark_normalized(uuid4())

    assert len(session.executed) == 1


def test_primary_of_returns_the_id_itself_when_it_is_not_a_duplicate() -> None:
    identifier = uuid4()
    session = FakeSession([FakeResult(None)])
    repository = SqlAlchemyDedupeRepository(session)

    assert repository.primary_of(identifier) == identifier


def test_primary_of_follows_a_chain_to_its_end() -> None:
    root = uuid4()
    middle = uuid4()
    leaf = uuid4()
    session = FakeSession([FakeResult(middle), FakeResult(root), FakeResult(None)])
    repository = SqlAlchemyDedupeRepository(session)

    assert repository.primary_of(leaf) == root


def test_the_repository_satisfies_the_dedupe_protocol() -> None:
    assert isinstance(SqlAlchemyDedupeRepository(FakeSession()), DedupeRepository)


def test_pending_selects_only_fetched_rows_with_a_body() -> None:
    session = FakeSession([FakeResult([])])
    repository = SqlAlchemyDedupeRepository(session)

    repository.pending(limit=5)

    rendered = str(session.executed[0])
    assert "processing_status" in rendered
    assert "raw_text IS NOT NULL" in rendered
