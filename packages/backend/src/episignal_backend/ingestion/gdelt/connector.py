"""Where a GDELT sighting and a publisher's page become one signal.

GDELT supplies the URL, the domain, and the moment its crawler saw the article.
The publisher's page supplies the headline, the publication time, and the text.
Neither is allowed to stand in for the other: a missing publication time stays
missing rather than borrowing the crawler's clock.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from episignal_backend.db.types import ProcessingStatus
from episignal_backend.diagnostics import FailureCategory
from episignal_backend.ingestion.documents import (
    DiscoveredArticle,
    DiscoveredSignal,
    Publisher,
    QueryRule,
    TimeWindow,
)
from episignal_backend.ingestion.fingerprint import content_hash
from episignal_backend.ingestion.gdelt.api import GdeltDocClient, GdeltRunSummary
from episignal_backend.ingestion.gdelt.article import ArticleFetcher, Disallowed, Unfetchable
from episignal_backend.ingestion.gdelt.extract import extract_page
from episignal_backend.ingestion.gdelt.ngram import GdeltNgramDiscovery, NgramDiscoveryResult
from episignal_backend.ingestion.protocol import RetrievalFailed

DISCOVERY_NAME = "GDELT"
MINIMUM_BODY_CHARACTERS = 200


def _utc_now() -> datetime:
    return datetime.now(UTC)


class GdeltConnector:
    discovery_name = DISCOVERY_NAME

    def __init__(
        self,
        search: GdeltDocClient | None = None,
        ngram: GdeltNgramDiscovery | None = None,
        fetcher: ArticleFetcher | None = None,
        now: Callable[[], datetime] = _utc_now,
        minimum_body_characters: int = MINIMUM_BODY_CHARACTERS,
    ) -> None:
        self._search = search
        self._ngram = ngram
        self._fetcher = fetcher or ArticleFetcher()
        self._now = now
        self._minimum_body_characters = minimum_body_characters

    @property
    def supports_batch_discovery(self) -> bool:
        return self._ngram is not None

    def discover(self, rule: QueryRule, window: TimeWindow) -> Sequence[DiscoveredArticle]:
        if self._search is None:
            raise RuntimeError("GDELT DOC discovery is not configured")
        return self._search.search(rule, window)

    def discover_rules(
        self, rules: Sequence[QueryRule], window: TimeWindow
    ) -> NgramDiscoveryResult:
        if self._ngram is None:
            raise RuntimeError("GDELT NGram discovery is not configured")
        return self._ngram.discover_rules(rules, window)

    def complete_discovery(self, cursor_after: datetime | None, *, success: bool) -> None:
        if self._ngram is not None:
            self._ngram.complete(cursor_after, success=success)

    def begin_discovery_run(self) -> None:
        if self._search is not None:
            self._search.begin_run()

    def finish_discovery_run(self, rules_total: int) -> GdeltRunSummary:
        if self._search is None:
            return GdeltRunSummary(
                rules_total=rules_total,
                rules_attempted=0,
                rules_succeeded=0,
                rules_failed=0,
                rules_skipped_circuit=0,
                https_attempts=0,
                http_attempts=0,
                failure_counts={},
                circuit_open=False,
                circuit_open_reason=None,
                failure_streak_elapsed_sec=0.0,
            )
        return self._search.finish_run(rules_total)

    def retrieve(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        try:
            html = self._fetcher.fetch(article.url)
        except (Unfetchable, Disallowed) as reason:
            raise RetrievalFailed(
                str(reason), category=getattr(reason, "category", None)
            ) from reason

        page = extract_page(html)
        # A page whose prose is shorter than a paragraph is a paywall notice or
        # a consent wall, not an article. Storing it would give sub-project C
        # nothing to read and would overstate what we hold.
        if len(page.body) < self._minimum_body_characters:
            raise RetrievalFailed(
                f"{article.domain} returned no article body",
                category=FailureCategory.INVALID_CONTENT.value,
            )

        title = page.title or article.title
        return DiscoveredSignal(
            url=article.url,
            canonical_url=article.canonical_url,
            title=title,
            raw_text=page.body,
            published_at=page.published_at,
            published_at_offset_minutes=page.published_at_offset_minutes,
            retrieved_at=self._now(),
            first_seen_at=first_seen_at,
            gdelt_seen_at=article.gdelt_seen_at,
            language=article.language,
            content_hash=content_hash(title, page.body),
            publisher=self._publisher(article, page.site_name),
            query_rule_id=article.query_rule_id,
            processing_status=ProcessingStatus.FETCHED,
        )

    def stub(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        """A discovery whose page could not be read.

        Kept rather than dropped: the sighting is itself evidence, a user can
        still open the original URL, and the row stays countable as a failure.
        The hash covers the title alone, because there is no body to cover.
        """
        return DiscoveredSignal(
            url=article.url,
            canonical_url=article.canonical_url,
            title=article.title,
            raw_text=None,
            published_at=None,
            published_at_offset_minutes=None,
            retrieved_at=self._now(),
            first_seen_at=first_seen_at,
            gdelt_seen_at=article.gdelt_seen_at,
            language=article.language,
            content_hash=content_hash(article.title, ""),
            publisher=self._publisher(article, None),
            query_rule_id=article.query_rule_id,
            processing_status=ProcessingStatus.FETCHED,
        )

    def defer(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        """A sighting stored before anyone has asked the publisher for the page.

        Distinct from `stub`, which records a page that was asked for and
        refused: this one is `fetched` and selectable by the retrieve stage,
        because nothing has gone wrong with it. The hash covers the title
        alone; `promote` recomputes it when the body arrives.
        """
        return DiscoveredSignal(
            url=article.url,
            canonical_url=article.canonical_url,
            title=article.title,
            raw_text=None,
            published_at=None,
            published_at_offset_minutes=None,
            retrieved_at=self._now(),
            first_seen_at=first_seen_at,
            gdelt_seen_at=article.gdelt_seen_at,
            language=article.language,
            content_hash=content_hash(article.title, ""),
            publisher=self._publisher(article, None),
            query_rule_id=article.query_rule_id,
            processing_status=ProcessingStatus.FETCHED,
        )

    def _publisher(self, article: DiscoveredArticle, site_name: str | None) -> Publisher:
        return Publisher(
            domain=article.domain,
            name=site_name or article.domain,
            language=article.language,
            country_code=article.country_code,
        )
