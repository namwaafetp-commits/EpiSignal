from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from episignal_backend.db.types import ProcessingStatus
from episignal_backend.ingestion.discovery import (
    DiscoveryResult,
    run_discovery,
)
from episignal_backend.ingestion.documents import (
    DiscoveredArticle,
    DiscoveredSignal,
    Publisher,
    QueryRule,
    TimeWindow,
)
from episignal_backend.ingestion.gdelt.api import GdeltUnavailable
from episignal_backend.ingestion.protocol import RetrievalFailed

NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
SEEN = datetime(2026, 8, 26, 7, 45, tzinfo=UTC)
RULE = QueryRule(id=uuid4(), rule_group="syndromic", query='"unknown fever"', label="Unknown fever")


def article(path: str, domain: str = "example.vn") -> DiscoveredArticle:
    return DiscoveredArticle(
        url=f"https://{domain}{path}",
        canonical_url=f"https://{domain}{path}",
        title=f"Report {path}",
        domain=domain,
        gdelt_seen_at=SEEN,
        language="vi",
        country_code="VN",
        query_rule_id=RULE.id,
    )


class FakeRepository:
    def __init__(self, seen: set[str] | None = None) -> None:
        self.seen = seen or set()
        self.added: list[tuple[DiscoveredSignal, UUID]] = []
        self.publishers: dict[str, UUID] = {}
        self.commits = 0
        self.rollbacks = 0
        self.first_seen: dict[str, datetime] = {}

    def active_rules(self) -> Sequence[QueryRule]:
        return (RULE,)

    def seen_urls(self, canonical_urls: Sequence[str]) -> frozenset[str]:
        return frozenset(url for url in canonical_urls if url in self.seen)

    def first_seen_at(self, canonical_url: str) -> datetime | None:
        return self.first_seen.get(canonical_url)

    def publisher_source_id(self, publisher: Publisher) -> UUID:
        if publisher.domain not in self.publishers:
            self.publishers[publisher.domain] = uuid4()
        return self.publishers[publisher.domain]

    def add(self, signal: DiscoveredSignal, source_id: UUID) -> None:
        self.added.append((signal, source_id))

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeConnector:
    discovery_name = "GDELT"

    def __init__(
        self,
        articles: tuple[DiscoveredArticle, ...] = (),
        failing: frozenset[str] = frozenset(),
        unavailable: bool = False,
    ) -> None:
        self.articles = articles
        self.failing = failing
        self.unavailable = unavailable
        self.retrieved: list[str] = []

    def discover(self, rule: QueryRule, window: TimeWindow) -> Sequence[DiscoveredArticle]:
        if self.unavailable:
            raise GdeltUnavailable("refused")
        return self.articles

    def retrieve(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        self.retrieved.append(article.canonical_url)
        if article.canonical_url in self.failing:
            raise RetrievalFailed("blocked")
        return self._signal(article, first_seen_at, ProcessingStatus.FETCHED, "Body text here.")

    def stub(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        return self._signal(article, first_seen_at, ProcessingStatus.NEEDS_REVIEW, None)

    def _signal(
        self,
        article: DiscoveredArticle,
        first_seen_at: datetime,
        status: ProcessingStatus,
        body: str | None,
    ) -> DiscoveredSignal:
        return DiscoveredSignal(
            url=article.url,
            canonical_url=article.canonical_url,
            title=article.title,
            raw_text=body,
            retrieved_at=NOW,
            first_seen_at=first_seen_at,
            gdelt_seen_at=article.gdelt_seen_at,
            language=article.language,
            content_hash=f"{abs(hash(article.canonical_url + str(status))):064x}"[:64],
            publisher=Publisher(
                domain=article.domain, name=article.domain, language="vi", country_code="VN"
            ),
            query_rule_id=article.query_rule_id,
            processing_status=status,
        )


def run(connector: FakeConnector, repository: FakeRepository, **kwargs: object) -> DiscoveryResult:
    return run_discovery(repository, connector, now=NOW, **kwargs)  # type: ignore[arg-type]


def test_stores_a_discovered_article() -> None:
    repository = FakeRepository()
    result = run(FakeConnector((article("/a"),)), repository)
    assert result.stored == 1
    assert repository.added[0][0].canonical_url == "https://example.vn/a"


def test_already_seen_urls_are_never_retrieved() -> None:
    repository = FakeRepository(seen={"https://example.vn/a"})
    connector = FakeConnector((article("/a"), article("/b")))
    result = run(connector, repository)

    # The ordering that matters: a URL already stored costs no page fetch.
    assert connector.retrieved == ["https://example.vn/b"]
    assert result.duplicate == 1
    assert result.stored == 1


def test_the_per_run_cap_bounds_retrieval() -> None:
    repository = FakeRepository()
    connector = FakeConnector(tuple(article(f"/{index}") for index in range(10)))
    result = run(connector, repository, max_articles=3)
    assert len(connector.retrieved) == 3
    assert result.stored == 3
    assert result.deferred == 7


def test_the_cap_takes_the_oldest_sightings_first() -> None:
    repository = FakeRepository()
    older = DiscoveredArticle(
        url="https://example.vn/old",
        canonical_url="https://example.vn/old",
        title="Older",
        domain="example.vn",
        gdelt_seen_at=SEEN - timedelta(hours=2),
    )
    connector = FakeConnector((article("/new"), older))
    run(connector, repository, max_articles=1)
    assert connector.retrieved == ["https://example.vn/old"]


def test_a_failed_retrieval_stores_a_stub_and_continues() -> None:
    repository = FakeRepository()
    connector = FakeConnector(
        (article("/a"), article("/b")), failing=frozenset({"https://example.vn/a"})
    )
    result = run(connector, repository)

    assert result.stored == 1
    assert result.needs_review == 1
    statuses = {signal.canonical_url: signal.processing_status for signal, _ in repository.added}
    assert statuses["https://example.vn/a"] is ProcessingStatus.NEEDS_REVIEW
    assert statuses["https://example.vn/b"] is ProcessingStatus.FETCHED


def test_publisher_registration_is_reused_within_a_run() -> None:
    repository = FakeRepository()
    run(FakeConnector((article("/a"), article("/b"))), repository)
    assert len(repository.publishers) == 1
    assert repository.added[0][1] == repository.added[1][1]


def test_two_publishers_get_two_sources() -> None:
    repository = FakeRepository()
    run(FakeConnector((article("/a"), article("/b", domain="other.vn"))), repository)
    assert len(repository.publishers) == 2


def test_a_known_url_keeps_its_original_first_seen_time() -> None:
    earlier = NOW - timedelta(days=3)
    repository = FakeRepository()
    repository.first_seen["https://example.vn/a"] = earlier
    run(FakeConnector((article("/a"),)), repository)
    assert repository.added[0][0].first_seen_at == earlier


def test_a_new_url_is_first_seen_now() -> None:
    repository = FakeRepository()
    run(FakeConnector((article("/a"),)), repository)
    assert repository.added[0][0].first_seen_at == NOW


def test_an_unavailable_rule_is_counted_not_raised() -> None:
    repository = FakeRepository()
    result = run(FakeConnector(unavailable=True), repository)
    assert result.rules_failed == 1
    assert result.stored == 0


def test_a_run_with_no_rules_reports_no_rules() -> None:
    class NoRules(FakeRepository):
        def active_rules(self) -> Sequence[QueryRule]:
            return ()

    result = run(FakeConnector(), NoRules())
    assert result.rules_run == 0


def test_the_window_ends_at_the_run_time() -> None:
    captured: list[TimeWindow] = []

    class Recording(FakeConnector):
        def discover(self, rule: QueryRule, window: TimeWindow) -> Sequence[DiscoveredArticle]:
            captured.append(window)
            return ()

    run(Recording(), FakeRepository(), window_minutes=20)
    assert captured[0].end == NOW
    assert captured[0].start == NOW - timedelta(minutes=20)


def test_a_storage_failure_rolls_back_and_continues() -> None:
    class Failing(FakeRepository):
        def add(self, signal: DiscoveredSignal, source_id: UUID) -> None:
            if signal.canonical_url.endswith("/a"):
                raise RuntimeError("constraint violated")
            super().add(signal, source_id)

    repository = Failing()
    result = run(FakeConnector((article("/a"), article("/b"))), repository)
    assert result.failed == 1
    assert result.stored == 1
    assert repository.rollbacks == 1
