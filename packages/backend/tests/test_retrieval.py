from datetime import UTC, datetime
from uuid import UUID, uuid4

from episignal_backend.db.types import FilterRuleGroup, ProcessingStatus
from episignal_backend.ingestion.documents import (
    DiscoveredArticle,
    DiscoveredSignal,
    FilterRule,
    Publisher,
    StubRetrieval,
)
from episignal_backend.ingestion.protocol import RetrievalFailed
from episignal_backend.ingestion.retrieval import run_retrieval

NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
SEEN = datetime(2026, 8, 26, 7, 45, tzinfo=UTC)
FIRST = datetime(2026, 8, 20, 6, 0, tzinfo=UTC)

OUTBREAK = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.TITLE_INCLUSION,
    pattern="outbreak",
    label="Context: outbreak",
)


def make_article(title: str, url: str) -> DiscoveredArticle:
    return DiscoveredArticle(
        url=url,
        canonical_url=url,
        title=title,
        domain="example.vn",
        gdelt_seen_at=SEEN,
    )


def make_stub(title: str, url: str) -> StubRetrieval:
    return StubRetrieval(
        signal_id=uuid4(),
        article=make_article(title, url),
        first_seen_at=FIRST,
        attempts=0,
    )


STADIUM = make_stub("City council approves new stadium", "https://example.vn/stadium")
MEASLES_STORY = make_stub("Measles outbreak spreads in Hanoi", "https://example.vn/measles")
SECOND_STORY = make_stub("Cholera outbreak declared in Capital", "https://example.vn/cholera")
COPY = make_stub(
    "Measles outbreak spreads in Hanoi | Example News",
    "https://copy.example.vn/measles",
)
ORIGINAL_ID = uuid4()


class FakeRetrievalRepository:
    def __init__(
        self,
        waiting: tuple[StubRetrieval, ...],
        rules: tuple[FilterRule, ...],
        promotable: bool = True,
        failing_ids: set[UUID] | None = None,
        titles: dict[str, UUID] | None = None,
    ) -> None:
        self.waiting = waiting
        self.rules = rules
        self.promotable = promotable
        self.failing_ids = failing_ids or set()
        self.titles = titles or {}
        self.filtered: list[UUID] = []
        self.duplicated: list[tuple[UUID, UUID]] = []
        self.promoted: list[UUID] = []
        self.failed_attempts: list[UUID] = []
        self.commits = 0
        self.rollbacks = 0
        self.deleted: list[UUID] = []
        self.title_lookups = 0

    def gated_awaiting_retrieval(
        self, *, max_attempts: int, limit: int
    ) -> tuple[StubRetrieval, ...]:
        return self.waiting[:limit]

    def keyword_rules(self) -> tuple[FilterRule, ...]:
        return self.rules

    def record_filtered(self, signal_id: UUID) -> None:
        if signal_id in self.failing_ids:
            raise RuntimeError("DB error")
        self.filtered.append(signal_id)

    def title_duplicate_of(self, normalized_title: str, *, within_hours: int) -> UUID | None:
        self.title_lookups += 1
        return self.titles.get(normalized_title)

    def mark_title_duplicate(self, signal_id: UUID, primary_id: UUID) -> None:
        self.duplicated.append((signal_id, primary_id))

    def promote(self, signal_id: UUID, signal: DiscoveredSignal) -> bool:
        if signal_id in self.failing_ids:
            raise RuntimeError("DB error")
        if not self.promotable:
            return False
        self.promoted.append(signal_id)
        return True

    def record_failed_attempt(self, signal_id: UUID, *, max_attempts: int = 3) -> None:
        if signal_id in self.failing_ids:
            raise RuntimeError("DB error")
        self.failed_attempts.append(signal_id)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class CountingConnector:
    discovery_name = "GDELT"

    def __init__(self, failing: bool = False) -> None:
        self.failing = failing
        self.retrieved = 0

    def retrieve(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        if self.failing:
            raise RetrievalFailed("mock error")
        self.retrieved += 1
        return DiscoveredSignal(
            url=article.url,
            canonical_url=article.canonical_url,
            title=article.title,
            raw_text="The body",
            published_at=NOW,
            published_at_offset_minutes=0,
            retrieved_at=NOW,
            first_seen_at=first_seen_at,
            gdelt_seen_at=article.gdelt_seen_at,
            language="en",
            content_hash="a" * 64,
            publisher=Publisher(
                domain=article.domain, name=article.domain, language="en", country_code="VN"
            ),
            processing_status=ProcessingStatus.FETCHED,
        )


def test_a_gated_title_is_filtered_and_never_fetched() -> None:
    repository = FakeRetrievalRepository(waiting=(STADIUM,), rules=(OUTBREAK,))
    connector = CountingConnector()

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)  # type: ignore[arg-type]

    assert result.filtered == 1
    assert result.retrieved == 0
    assert connector.retrieved == 0
    assert repository.filtered == [STADIUM.signal_id]


def test_a_passing_title_is_fetched_exactly_once() -> None:
    repository = FakeRetrievalRepository(waiting=(MEASLES_STORY,), rules=(OUTBREAK,))
    connector = CountingConnector()

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)  # type: ignore[arg-type]

    assert result.retrieved == 1
    assert connector.retrieved == 1
    assert repository.promoted == [MEASLES_STORY.signal_id]


def test_an_unfetchable_page_records_a_failed_attempt() -> None:
    repository = FakeRetrievalRepository(waiting=(MEASLES_STORY,), rules=(OUTBREAK,))
    connector = CountingConnector(failing=True)

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)  # type: ignore[arg-type]

    assert result.still_failing == 1
    assert repository.failed_attempts == [MEASLES_STORY.signal_id]
    assert repository.filtered == []


def test_a_redundant_promotion_is_counted_not_failed() -> None:
    repository = FakeRetrievalRepository(
        waiting=(MEASLES_STORY,), rules=(OUTBREAK,), promotable=False
    )
    connector = CountingConnector()

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)  # type: ignore[arg-type]

    assert result.redundant == 1
    assert result.retrieved == 0


def test_a_storage_failure_rolls_back_and_keeps_going() -> None:
    repository = FakeRetrievalRepository(
        waiting=(MEASLES_STORY, SECOND_STORY),
        rules=(OUTBREAK,),
        failing_ids={MEASLES_STORY.signal_id},
    )
    connector = CountingConnector()

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)  # type: ignore[arg-type]

    assert result.failed == 1
    assert result.retrieved == 1
    assert repository.rollbacks == 1


def test_no_signal_is_ever_deleted() -> None:
    repository = FakeRetrievalRepository(waiting=(STADIUM, MEASLES_STORY), rules=(OUTBREAK,))
    connector = CountingConnector()

    run_retrieval(repository, connector, max_attempts=3, batch_size=10)  # type: ignore[arg-type]

    assert repository.deleted == []


def test_a_syndicated_copy_is_marked_duplicate_before_it_is_fetched() -> None:
    repository = FakeRetrievalRepository(
        waiting=(COPY,), rules=(OUTBREAK,), titles={COPY.normalized_title: ORIGINAL_ID}
    )
    connector = CountingConnector()

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)  # type: ignore[arg-type]

    assert result.duplicates == 1
    assert connector.retrieved == 0
    assert repository.duplicated == [(COPY.signal_id, ORIGINAL_ID)]


def test_a_title_match_outside_the_window_is_still_fetched() -> None:
    repository = FakeRetrievalRepository(waiting=(COPY,), rules=(OUTBREAK,), titles={})
    connector = CountingConnector()

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)  # type: ignore[arg-type]

    assert result.duplicates == 0
    assert connector.retrieved == 1


def test_the_gate_runs_before_the_title_check() -> None:
    repository = FakeRetrievalRepository(waiting=(STADIUM,), rules=(OUTBREAK,), titles={})

    result = run_retrieval(  # type: ignore[arg-type]
        repository, CountingConnector(), max_attempts=3, batch_size=10
    )

    assert result.filtered == 1
    assert repository.title_lookups == 0
