"""Ingestion decisions.

This module imports neither SQLAlchemy nor httpx. It depends on the two
Protocols in `protocol.py`, which is what makes every decision below testable
with in-memory fakes and no credentials.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from episignal_backend.ingestion.protocol import SignalRepository, SourceConnector

DEFAULT_WINDOW_DAYS = 90

logger = logging.getLogger("episignal_backend.ingestion")


class MissingSourceError(Exception):
    """The connector's source identity has not been seeded."""


@dataclass(frozen=True)
class IngestionResult:
    inserted: int
    skipped: int
    failed: int


def run_ingestion(
    repository: SignalRepository,
    connector: SourceConnector,
    *,
    since: datetime | None = None,
    now: datetime | None = None,
) -> IngestionResult:
    moment = now or datetime.now(UTC)

    source_id = repository.source_id(connector.source_name)
    if source_id is None:
        raise MissingSourceError(connector.source_name)

    window_start = since or (moment - timedelta(days=DEFAULT_WINDOW_DAYS))

    inserted = 0
    skipped = 0
    failed = 0

    for document in connector.fetch(window_start, inclusive=since is not None):
        try:
            signal = connector.normalize(document)
            if repository.exists(signal.url, signal.content_hash):
                skipped += 1
                continue
            repository.add(signal, source_id)
            repository.commit()
            inserted += 1
        except Exception as error:
            repository.rollback()
            failed += 1
            logger.error(
                "Could not ingest document %s from %s (%s)",
                document.source_url or "<unknown URL>",
                connector.source_name,
                type(error).__name__,
            )

    repository.activate(source_id)
    repository.commit()

    return IngestionResult(inserted=inserted, skipped=skipped, failed=failed)
