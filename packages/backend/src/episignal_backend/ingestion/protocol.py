"""The two boundaries the pipeline depends on.

`pipeline.py` imports these Protocols and nothing else, so every ingestion
decision is testable with in-memory fakes: no database, no network, no
credentials.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from episignal_backend.ingestion.documents import NormalizedSignal, RawDocument


@runtime_checkable
class SourceConnector(Protocol):
    source_name: str

    def fetch(self, since: datetime, *, inclusive: bool = False) -> Sequence[RawDocument]: ...

    def normalize(self, document: RawDocument) -> NormalizedSignal: ...


@runtime_checkable
class SignalRepository(Protocol):
    def source_id(self, name: str) -> UUID | None: ...

    def latest_published_at(self, source_id: UUID) -> datetime | None: ...

    def exists(self, url: str, content_hash: str) -> bool: ...

    def add(self, signal: NormalizedSignal, source_id: UUID) -> None: ...

    def activate(self, source_id: UUID) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
