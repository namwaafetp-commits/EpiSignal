"""The boundaries the pipeline depends on.

`pipeline.py` and `discovery.py` import these Protocols and nothing else, so
every ingestion decision is testable with in-memory fakes: no database, no
network, no credentials.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from episignal_backend.ingestion.documents import (
    ComparableSignal,
    DiscoveredArticle,
    DiscoveredSignal,
    FilterRule,
    NormalizedSignal,
    Publisher,
    QueryRule,
    RawDocument,
    Rejection,
    StubRetrieval,
    TimeWindow,
)


@runtime_checkable
class SourceConnector(Protocol):
    source_name: str

    def fetch(self, since: datetime, *, inclusive: bool = False) -> Sequence[RawDocument]: ...

    def normalize(self, document: RawDocument) -> NormalizedSignal: ...


@runtime_checkable
class SignalRepository(Protocol):
    def source_id(self, name: str) -> UUID | None: ...

    def exists(self, url: str, content_hash: str) -> bool: ...

    def add(self, signal: NormalizedSignal, source_id: UUID) -> None: ...

    def activate(self, source_id: UUID) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@runtime_checkable
class DiscoveryConnector(Protocol):
    """A radar: it finds articles other people published.

    Distinct from `SourceConnector`, which speaks for exactly one known
    publisher. `discover` returns metadata only and opens no publisher
    connection, so the pipeline can drop already-seen URLs before paying for a
    page fetch.
    """

    discovery_name: str

    def discover(self, rule: QueryRule, window: TimeWindow) -> Sequence[DiscoveredArticle]: ...

    def retrieve(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal: ...

    def stub(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal: ...

    def defer(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal: ...



@runtime_checkable
class DiscoveryRepository(Protocol):
    def active_rules(self) -> Sequence[QueryRule]: ...

    def filter_rules(self) -> Sequence[FilterRule]: ...

    def keyword_rules(self) -> Sequence[FilterRule]: ...

    def record_rejection(self, rejection: Rejection) -> None: ...

    def seen_urls(self, canonical_urls: Sequence[str]) -> frozenset[str]: ...

    def first_seen_at(self, canonical_url: str) -> datetime | None: ...

    def publisher_source_id(self, publisher: Publisher) -> UUID: ...

    def add(self, signal: DiscoveredSignal, source_id: UUID) -> None: ...

    def stubs_awaiting_retrieval(
        self, *, max_attempts: int, limit: int
    ) -> Sequence[StubRetrieval]: ...

    def gated_awaiting_retrieval(
        self, *, max_attempts: int, limit: int
    ) -> Sequence[StubRetrieval]: ...

    def record_filtered(self, signal_id: UUID) -> None: ...


    def promote(self, signal_id: UUID, signal: DiscoveredSignal) -> bool: ...

    def record_failed_attempt(self, signal_id: UUID, *, max_attempts: int = 3) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


@runtime_checkable
class DedupeRepository(Protocol):
    """The storage boundary for Stage 0's second gate.

    Separate from `DiscoveryRepository` because this pass never discovers, never
    fetches, and never registers a publisher. A pass that reads stored signals
    and writes their status has no business holding a handle that can open a
    GDELT query.
    """

    def pending(self, *, limit: int) -> Sequence[ComparableSignal]: ...

    def candidates(
        self, signal: ComparableSignal, *, window_hours: int
    ) -> Sequence[ComparableSignal]: ...

    def primary_of(self, signal_id: UUID) -> UUID: ...

    def mark_duplicate(self, signal_id: UUID, primary_id: UUID) -> None: ...

    def mark_normalized(self, signal_id: UUID) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class UnsupportedDocument(Exception):
    """The source returned a document this connector does not ingest.

    Distinct from a failure: the source is healthy and the connector understood
    it, but the document carries no evidence this connector can store. Raising
    it keeps the document visible in the run's counts without turning a normal
    run into an error.
    """


class RetrievalFailed(Exception):
    """The publisher's page could not be turned into evidence.

    Distinct from `UnsupportedDocument`: the article is wanted, and the
    discovery is kept as a stub for retry, rather than rejected outright.
    """
