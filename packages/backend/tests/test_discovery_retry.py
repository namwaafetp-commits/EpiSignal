from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from episignal_backend.db.types import ProcessingStatus
from episignal_backend.ingestion.discovery import RetryResult, run_retry
from episignal_backend.ingestion.documents import (
    DiscoveredArticle,
    DiscoveredSignal,
    Publisher,
    StubRetrieval,
)
from episignal_backend.ingestion.protocol import RetrievalFailed

NOW = datetime(2026, 8, 26, 9, 0, tzinfo=UTC)
SEEN = datetime(2026, 8, 26, 7, 45, tzinfo=UTC)
FIRST = datetime(2026, 8, 20, 6, 0, tzinfo=UTC)


def article(path: str = "/a") -> DiscoveredArticle:
    return DiscoveredArticle(
        url=f"https://example.vn{path}",
        canonical_url=f"https://example.vn{path}",
        title=f"Report {path}",
        domain="example.vn",
        gdelt_seen_at=SEEN,
        language="vi",
        country_code="VN",
    )


def stub(signal_id: UUID, attempts: int = 0, path: str = "/a") -> StubRetrieval:
    return StubRetrieval(
        signal_id=signal_id, article=article(path), first_seen_at=FIRST, attempts=attempts
    )


class FakeRepository:
    def __init__(self, stubs: tuple[StubRetrieval, ...], conflicting: bool = False) -> None:
        self.stubs = stubs
        self.conflicting = conflicting
        self.promoted: list[tuple[UUID, DiscoveredSignal]] = []
        self.failed_attempts: list[UUID] = []
        self.commits = 0
        self.rollbacks = 0
        self.selection: list[tuple[int, int]] = []

    def stubs_awaiting_retrieval(
        self, *, max_attempts: int, limit: int
    ) -> Sequence[StubRetrieval]:
        self.selection.append((max_attempts, limit))
        return self.stubs

    def promote(self, signal_id: UUID, signal: DiscoveredSignal) -> bool:
        self.promoted.append((signal_id, signal))
        return not self.conflicting

    def record_failed_attempt(self, signal_id: UUID) -> None:
        self.failed_attempts.append(signal_id)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeConnector:
    discovery_name = "GDELT"

    def __init__(self, failing: frozenset[str] = frozenset()) -> None:
        self.failing = failing
        self.retrieved: list[str] = []

    def retrieve(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        self.retrieved.append(article.canonical_url)
        if article.canonical_url in self.failing:
            raise RetrievalFailed("still blocked")
        return DiscoveredSignal(
            url=article.url,
            canonical_url=article.canonical_url,
            title=article.title,
            raw_text="The article text.",
            published_at=NOW,
            published_at_offset_minutes=420,
            retrieved_at=NOW,
            first_seen_at=first_seen_at,
            gdelt_seen_at=article.gdelt_seen_at,
            language=article.language,
            content_hash="e" * 64,
            publisher=Publisher(
                domain=article.domain, name=article.domain, language="vi", country_code="VN"
            ),
            processing_status=ProcessingStatus.FETCHED,
        )


def run(repository: FakeRepository, connector: FakeConnector, **kwargs: object) -> RetryResult:
    return run_retry(repository, connector, **kwargs)  # type: ignore[arg-type]


def test_a_successful_retry_promotes_the_stub_in_place() -> None:
    signal_id = uuid4()
    repository = FakeRepository((stub(signal_id),))
    result = run(repository, FakeConnector())

    assert result.promoted == 1
    assert repository.promoted[0][0] == signal_id
    assert repository.promoted[0][1].raw_text == "The article text."


def test_a_retry_keeps_the_original_first_seen_time() -> None:
    repository = FakeRepository((stub(uuid4()),))
    run(repository, FakeConnector())
    # Resetting this would silently destroy the detection-lead-time metric.
    assert repository.promoted[0][1].first_seen_at == FIRST


def test_a_repeated_failure_counts_the_attempt_without_promoting() -> None:
    signal_id = uuid4()
    repository = FakeRepository((stub(signal_id),))
    connector = FakeConnector(failing=frozenset({"https://example.vn/a"}))
    result = run(repository, connector)

    assert result.promoted == 0
    assert result.still_failing == 1
    assert repository.promoted == []
    assert repository.failed_attempts == [signal_id]


def test_a_promotion_conflict_counts_the_attempt_and_keeps_going() -> None:
    repository = FakeRepository((stub(uuid4()), stub(uuid4(), path="/b")), conflicting=True)
    result = run(repository, FakeConnector())

    assert result.promoted == 0
    assert result.redundant == 2
    assert len(repository.promoted) == 2


def test_the_attempt_budget_and_batch_size_are_passed_to_the_selection() -> None:
    repository = FakeRepository(())
    run(repository, FakeConnector(), max_attempts=5, batch_size=25)
    # The budget is enforced in the query, so an exhausted stub is never fetched.
    assert repository.selection == [(5, 25)]


def test_a_run_with_no_stubs_does_nothing() -> None:
    repository = FakeRepository(())
    connector = FakeConnector()
    result = run(repository, connector)

    assert result == RetryResult()
    assert connector.retrieved == []


def test_a_storage_failure_rolls_back_and_continues() -> None:
    class Failing(FakeRepository):
        def promote(self, signal_id: UUID, signal: DiscoveredSignal) -> bool:
            if signal.canonical_url.endswith("/a"):
                raise RuntimeError("connection lost")
            return super().promote(signal_id, signal)

    repository = Failing((stub(uuid4()), stub(uuid4(), path="/b")))
    result = run(repository, FakeConnector())

    assert result.failed == 1
    assert result.promoted == 1
    assert repository.rollbacks == 1
