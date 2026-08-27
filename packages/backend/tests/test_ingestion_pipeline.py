import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from episignal_backend.ingestion.documents import NormalizedSignal, RawDocument
from episignal_backend.ingestion.fingerprint import content_hash
from episignal_backend.ingestion.pipeline import (
    DEFAULT_WINDOW_DAYS,
    MissingSourceError,
    run_ingestion,
)
from episignal_backend.ingestion.protocol import UnsupportedDocument

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
SOURCE = "WHO Disease Outbreak News"
URL = "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615"
TITLE = "Ebola disease - Democratic Republic of the Congo"


def digest(content: str) -> str:
    # Real digests, not synthetic ones: NormalizedSignal requires lowercase hex,
    # and deriving them here keeps the sentinel wording free to be anything.
    return content_hash(TITLE, content)


def signal(content: str = "a") -> NormalizedSignal:
    return NormalizedSignal(
        external_id="2026-DON615",
        url=URL,
        canonical_url=URL,
        title=TITLE,
        raw_text=content,
        published_at=NOW - timedelta(days=1),
        retrieved_at=NOW,
        content_hash=digest(content),
    )


class FakeRepository:
    def __init__(self, source: UUID | None = None) -> None:
        self._source = source if source is not None else uuid4()
        self.stored: list[tuple[str, str]] = []
        self.latest: datetime | None = None
        self.activated = False
        self.commits = 0
        self.rollbacks = 0
        self.missing = False

    def source_id(self, name: str) -> UUID | None:
        return None if self.missing else self._source

    # Regression guard: the pipeline must ignore a cursor exposed by an older
    # adapter because partially stored rows cannot safely advance the window.
    def latest_published_at(self, source_id: UUID) -> datetime | None:
        return self.latest

    def exists(self, url: str, content_hash: str) -> bool:
        return (url, content_hash) in self.stored

    def add(self, item: NormalizedSignal, source_id: UUID) -> None:
        if item.raw_text == "explode":
            raise RuntimeError("cannot store this document")
        self.stored.append((item.url, item.content_hash))

    def activate(self, source_id: UUID) -> None:
        self.activated = True

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeConnector:
    source_name = SOURCE

    def __init__(self, signals: Sequence[NormalizedSignal]) -> None:
        self._signals = signals
        self.since: datetime | None = None
        self.inclusive: bool | None = None

    def fetch(self, since: datetime, *, inclusive: bool = False) -> Sequence[RawDocument]:
        self.since = since
        self.inclusive = inclusive
        return [
            RawDocument(payload={"index": index}, retrieved_at=NOW, source_url=URL)
            for index in range(len(self._signals))
        ]

    def normalize(self, document: RawDocument) -> NormalizedSignal:
        index = int(document.payload["index"])
        if self._signals[index].raw_text == "unparseable":
            raise ValueError("cannot normalize this document")
        if self._signals[index].raw_text == "unsupported":
            raise UnsupportedDocument("page carries no article body")
        return self._signals[index]


def test_an_unseen_document_is_inserted() -> None:
    repository = FakeRepository()
    result = run_ingestion(repository, FakeConnector([signal()]), now=NOW)
    assert (result.inserted, result.skipped, result.failed) == (1, 0, 0)
    assert repository.stored == [(URL, digest("a"))]


def test_the_same_document_is_skipped_on_a_second_run() -> None:
    repository = FakeRepository()
    run_ingestion(repository, FakeConnector([signal()]), now=NOW)
    result = run_ingestion(repository, FakeConnector([signal()]), now=NOW)
    assert (result.inserted, result.skipped, result.failed) == (0, 1, 0)
    assert len(repository.stored) == 1


def test_a_revised_document_is_stored_as_another_version() -> None:
    repository = FakeRepository()
    run_ingestion(repository, FakeConnector([signal("a")]), now=NOW)
    result = run_ingestion(repository, FakeConnector([signal("b")]), now=NOW)
    assert result.inserted == 1
    assert len(repository.stored) == 2
    assert {url for url, _ in repository.stored} == {URL}


def test_one_unparseable_document_does_not_stop_the_others() -> None:
    repository = FakeRepository()
    connector = FakeConnector([signal("unparseable"), signal("c")])
    result = run_ingestion(repository, connector, now=NOW)
    assert (result.inserted, result.skipped, result.failed) == (1, 0, 1)
    assert repository.stored == [(URL, digest("c"))]


def test_a_storage_failure_rolls_back_only_that_document() -> None:
    repository = FakeRepository()
    connector = FakeConnector([signal("explode"), signal("d")])
    result = run_ingestion(repository, connector, now=NOW)
    assert (result.inserted, result.failed) == (1, 1)
    assert repository.rollbacks == 1


def test_each_stored_document_is_committed_individually() -> None:
    repository = FakeRepository()
    connector = FakeConnector([signal("e"), signal("f")])
    run_ingestion(repository, connector, now=NOW)
    assert repository.commits >= 2


def test_a_missing_source_aborts_before_fetching() -> None:
    repository = FakeRepository()
    repository.missing = True
    connector = FakeConnector([signal()])
    with pytest.raises(MissingSourceError, match=SOURCE):
        run_ingestion(repository, connector, now=NOW)
    assert connector.since is None
    assert connector.inclusive is None


def test_a_successful_run_activates_the_source() -> None:
    repository = FakeRepository()
    run_ingestion(repository, FakeConnector([signal()]), now=NOW)
    assert repository.activated is True


def test_the_first_run_uses_the_default_window() -> None:
    connector = FakeConnector([])
    run_ingestion(FakeRepository(), connector, now=NOW)
    assert connector.since == NOW - timedelta(days=DEFAULT_WINDOW_DAYS)
    assert connector.inclusive is False


def test_each_default_run_rechecks_the_activity_window() -> None:
    repository = FakeRepository()
    repository.latest = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    connector = FakeConnector([])
    run_ingestion(repository, connector, now=NOW)
    assert connector.since == NOW - timedelta(days=DEFAULT_WINDOW_DAYS)
    assert connector.inclusive is False


def test_an_explicit_since_overrides_the_default_window() -> None:
    connector = FakeConnector([])
    requested = datetime(2026, 1, 1, tzinfo=UTC)
    run_ingestion(FakeRepository(), connector, since=requested, now=NOW)
    assert connector.since == requested
    assert connector.inclusive is True


def test_a_document_failure_logs_its_url_without_evidence_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="episignal_backend.ingestion"):
        run_ingestion(FakeRepository(), FakeConnector([signal("explode")]), now=NOW)
    assert URL in caplog.text
    assert SOURCE in caplog.text
    assert "explode" not in caplog.text
    assert "cannot store this document" not in caplog.text


def test_an_unsupported_document_is_rejected_not_failed() -> None:
    # A source that publishes something outside a connector's scope is healthy.
    # Counting it as a failure would make every normal run exit non-zero.
    repository = FakeRepository()
    result = run_ingestion(repository, FakeConnector([signal("unsupported")]), now=NOW)
    assert (result.inserted, result.skipped, result.rejected, result.failed) == (0, 0, 1, 0)


def test_a_rejected_document_is_not_rolled_back() -> None:
    # Nothing was written, so a rollback would only obscure what happened.
    repository = FakeRepository()
    run_ingestion(repository, FakeConnector([signal("unsupported")]), now=NOW)
    assert repository.rollbacks == 0


def test_a_rejected_document_does_not_stop_the_run() -> None:
    repository = FakeRepository()
    result = run_ingestion(
        repository,
        FakeConnector([signal("unsupported"), signal("a")]),
        now=NOW,
    )
    assert (result.inserted, result.rejected, result.failed) == (1, 1, 0)
    assert repository.stored == [(URL, digest("a"))]


def test_a_failure_is_still_counted_as_a_failure() -> None:
    repository = FakeRepository()
    result = run_ingestion(repository, FakeConnector([signal("unparseable")]), now=NOW)
    assert (result.rejected, result.failed) == (0, 1)
    assert repository.rollbacks == 1


def test_a_run_with_no_rejections_reports_zero() -> None:
    repository = FakeRepository()
    result = run_ingestion(repository, FakeConnector([signal()]), now=NOW)
    assert result.rejected == 0
