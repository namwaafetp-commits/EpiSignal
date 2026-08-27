"""Where a GDELT sighting and a publisher's page become one signal.

GDELT supplies the URL, the domain, and the moment its crawler saw the article.
The publisher's page supplies the headline, the publication time, and the text.
Neither is allowed to stand in for the other: a missing publication time stays
missing rather than borrowing the crawler's clock.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from episignal_backend.db.types import ProcessingStatus
from episignal_backend.ingestion.documents import (
    DiscoveredArticle,
    DiscoveredSignal,
    Publisher,
    QueryRule,
    TimeWindow,
)
from episignal_backend.ingestion.fingerprint import content_hash
from episignal_backend.ingestion.gdelt.api import GdeltDocClient
from episignal_backend.ingestion.gdelt.article import ArticleFetcher, Disallowed, Unfetchable
from episignal_backend.ingestion.gdelt.extract import extract_page
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
        fetcher: ArticleFetcher | None = None,
        now: Callable[[], datetime] = _utc_now,
        minimum_body_characters: int = MINIMUM_BODY_CHARACTERS,
    ) -> None:
        self._search = search or GdeltDocClient()
        self._fetcher = fetcher or ArticleFetcher()
        self._now = now
        self._minimum_body_characters = minimum_body_characters

    def discover(self, rule: QueryRule, window: TimeWindow) -> Sequence[DiscoveredArticle]:
        return self._search.search(rule, window)

    def retrieve(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        try:
            html = self._fetcher.fetch(article.url)
        except (Unfetchable, Disallowed) as reason:
            raise RetrievalFailed(str(reason)) from reason

        page = extract_page(html)
        # A page whose prose is shorter than a paragraph is a paywall notice or
        # a consent wall, not an article. Storing it would give sub-project C
        # nothing to read and would overstate what we hold.
        if len(page.body) < self._minimum_body_characters:
            raise RetrievalFailed(f"{article.domain} returned no article body")

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
            processing_status=ProcessingStatus.NEEDS_REVIEW,
        )

    def _publisher(self, article: DiscoveredArticle, site_name: str | None) -> Publisher:
        return Publisher(
            domain=article.domain,
            name=site_name or article.domain,
            language=article.language,
            country_code=article.country_code,
        )
