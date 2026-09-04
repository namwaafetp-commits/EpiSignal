from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from episignal_backend.db.types import FilterRuleGroup, ProcessingStatus
from episignal_backend.ingestion.discovery import (
    DiscoveryResult,
    run_discovery,
)
from episignal_backend.ingestion.documents import (
    DiscoveredArticle,
    DiscoveredSignal,
    FilterRule,
    Publisher,
    QueryRule,
    Rejection,
    TimeWindow,
)
from episignal_backend.ingestion.gdelt.api import GdeltDocClient, GdeltUnavailable
from episignal_backend.ingestion.gdelt.connector import GdeltConnector
from episignal_backend.ingestion.protocol import RetrievalFailed
from episignal_backend.schedule.documents import StageName
from episignal_backend.schedule.run import run_chain

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
        self.rules: tuple[FilterRule, ...] = ()
        self.rejections: list[Rejection] = []
        self.rejection_fails = False

    def active_rules(self) -> Sequence[QueryRule]:
        return (RULE,)

    def filter_rules(self) -> Sequence[FilterRule]:
        return self.rules

    def record_rejection(self, rejection: Rejection) -> None:
        if self.rejection_fails:
            raise RuntimeError("rejection table unavailable")
        self.rejections.append(rejection)

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
        self.deferred: list[str] = []

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

    def defer(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        self.deferred.append(article.canonical_url)
        return self._signal(article, first_seen_at, ProcessingStatus.FETCHED, None)

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
    assert connector.deferred == ["https://example.vn/b"]
    assert result.duplicate == 1
    assert result.stored == 1


def test_the_per_run_cap_bounds_retrieval() -> None:
    repository = FakeRepository()
    connector = FakeConnector(tuple(article(f"/{index}") for index in range(10)))
    result = run(connector, repository, max_articles=3)
    assert len(connector.deferred) == 3
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
    assert connector.deferred == ["https://example.vn/old"]


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


METAPHOR = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.TITLE_EXCLUSION,
    pattern=r"\boutbreak of violence\b",
    label="Outbreak of violence",
)


def violent(path: str) -> DiscoveredArticle:
    return DiscoveredArticle(
        url=f"https://example.vn{path}",
        canonical_url=f"https://example.vn{path}",
        title="Outbreak of violence in the capital",
        domain="example.vn",
        gdelt_seen_at=SEEN,
        query_rule_id=RULE.id,
    )


def test_a_rejected_article_is_never_fetched() -> None:
    repository = FakeRepository()
    repository.rules = (METAPHOR,)
    connector = FakeConnector(articles=(violent("/a"),))

    result = run_discovery(repository, connector, now=NOW)

    assert connector.deferred == []
    assert repository.added == []
    assert result.rejected == 1
    assert result.stored == 0


def test_a_rejection_names_the_rule_that_caused_it() -> None:
    repository = FakeRepository()
    repository.rules = (METAPHOR,)
    connector = FakeConnector(articles=(violent("/a"),))

    run_discovery(repository, connector, now=NOW)

    assert len(repository.rejections) == 1
    assert repository.rejections[0].filter_rule_id == METAPHOR.id
    assert repository.rejections[0].canonical_url == "https://example.vn/a"
    assert repository.rejections[0].gdelt_seen_at == SEEN


def test_a_kept_article_is_still_fetched_and_stored() -> None:
    repository = FakeRepository()
    repository.rules = (METAPHOR,)
    connector = FakeConnector(articles=(article("/a"), violent("/b")))

    result = run_discovery(repository, connector, now=NOW)

    assert connector.deferred == ["https://example.vn/a"]
    assert result.stored == 1
    assert result.rejected == 1


def test_filtering_runs_before_the_per_run_cap() -> None:
    repository = FakeRepository()
    repository.rules = (METAPHOR,)
    connector = FakeConnector(articles=(violent("/a"), article("/b")))

    result = run_discovery(repository, connector, now=NOW, max_articles=1)

    # The one slot goes to the article worth having, not to the one about to be
    # thrown away.
    assert connector.deferred == ["https://example.vn/b"]
    assert result.deferred == 0


def test_an_invalid_rule_is_counted_and_does_not_stop_the_run() -> None:
    repository = FakeRepository()
    repository.rules = (
        FilterRule(
            id=uuid4(),
            rule_group=FilterRuleGroup.TITLE_EXCLUSION,
            pattern=r"([unclosed",
            label="Broken",
        ),
    )
    connector = FakeConnector(articles=(article("/a"),))

    result = run_discovery(repository, connector, now=NOW)

    assert result.rules_invalid == 1
    assert result.stored == 1


def test_an_article_survives_when_its_rejection_cannot_be_recorded() -> None:
    repository = FakeRepository()
    repository.rules = (METAPHOR,)
    repository.rejection_fails = True
    connector = FakeConnector(articles=(violent("/a"),))

    result = run_discovery(repository, connector, now=NOW)

    # A lost audit row must not also lose the article.
    assert connector.deferred == ["https://example.vn/a"]
    assert result.failed == 1
    assert result.rejected == 0


def test_discovery_defers_every_retrieval() -> None:
    repository = FakeRepository()
    connector = FakeConnector(articles=(article("/a"),))

    result = run_discovery(repository, connector, now=NOW)

    assert len(connector.retrieved) == 0
    assert len(connector.deferred) == 1
    assert result.stored == 1
    assert result.needs_review == 0
    assert repository.added[0][0].processing_status is ProcessingStatus.FETCHED
    assert repository.added[0][0].raw_text is None


def test_gdelt_circuit_open_returns_a_successful_stage_for_later_pipeline_stages() -> None:
    rules = tuple(
        QueryRule(
            id=uuid4(),
            rule_group="syndromic",
            query=f"rule-{index}",
            label=f"Rule {index}",
        )
        for index in range(9)
    )

    class ManyRules(FakeRepository):
        def active_rules(self) -> Sequence[QueryRule]:
            return rules

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    transport = httpx.MockTransport(handler)
    client = GdeltDocClient(
        client=httpx.Client(transport=transport),
        fallback_client=httpx.Client(transport=transport),
        sleep=lambda _: None,
    )
    discovery = GdeltConnector(search=client)  # type: ignore[arg-type]
    result = run_discovery(ManyRules(), discovery, now=NOW)

    called: list[str] = []
    outcome = run_chain(
        [StageName.DISCOVER, StageName.RETRIEVE],
        {
            StageName.DISCOVER: lambda: (
                called.append("discover")
                or {
                    "rules": result.rules_run,
                    "rules_failed": result.rules_failed,
                    "rules_skipped_circuit": result.rules_skipped_circuit,
                }
            ),
            StageName.RETRIEVE: lambda: called.append("retrieve") or {"retrieved": 0},
        },
    )

    assert result.rules_failed == 8
    assert result.rules_skipped_circuit == 1
    assert outcome.ok
    assert called == ["discover", "retrieve"]
