from __future__ import annotations

import gzip
import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from episignal_backend.db.types import ProcessingStatus
from episignal_backend.ingestion.discovery import run_discovery
from episignal_backend.ingestion.documents import QueryRule, TimeWindow
from episignal_backend.ingestion.gdelt.ngram import (
    GdeltNgramClient,
    GdeltNgramDiscovery,
    NgramBatch,
    NgramProviderStatus,
    NgramRunMetrics,
    TemporaryBatchFiles,
    match_rules,
    process_toc,
    scan_ngram,
    temporary_batch_files,
)

NOW = datetime(2026, 9, 10, 2, 0, tzinfo=UTC)
RULES = (
    QueryRule(id=None, rule_group="known_disease", query="dengue", label="Dengue", language="en"),
    QueryRule(
        id=None,
        rule_group="known_disease",
        query='"mers"',
        label="MERS",
        language="en",
    ),
)


class HeadResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> HeadResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_inventory_keeps_only_complete_pairs_and_bounds_scan() -> None:
    def opener(request: object, *, timeout: float) -> HeadResponse:
        url = str(getattr(request, "full_url", request))
        if url.endswith("020000.ngrams.txt.gz") or url.endswith("020000.toc.json.gz"):
            return HeadResponse(200)
        return HeadResponse(404)

    client = GdeltNgramClient(opener=opener)

    inventory = client.inventory(NOW - timedelta(minutes=2), NOW, max_batches=10)

    assert len(inventory.batches) == 1
    assert inventory.batches[0].timestamp == NOW
    assert inventory.ngram_files_seen == 1
    assert inventory.toc_files_seen == 1
    assert inventory.minutes_checked == 3


def test_ngram_matching_requires_token_boundaries_and_keeps_multiple_rules() -> None:
    assert match_rules("dengue mers", RULES) == ("Dengue", "MERS")
    assert match_rules("indengue mers", RULES) == ("MERS",)


def test_ngram_scan_streams_gzip_rows() -> None:
    payload = gzip.compress(b"7\tdengue mers\t1\n8\tindengue\t1\n")
    with gzip.open(io.BytesIO(payload), "rt", encoding="utf-8") as handle:
        assert scan_ngram(handle, RULES) == {7: {"Dengue", "MERS"}}


def test_toc_filters_rule_language_and_canonicalizes_duplicate_urls() -> None:
    toc = io.StringIO(
        '{"ID":7,"date":"2026-09-10T01:00:00.000Z","lang":"en",'
        '"title":"Dengue cases","url":"https://Example.org/a?utm_source=x"}\n'
        '{"ID":8,"date":"2026-09-10T01:01:00.000Z","lang":"fr",'
        '"title":"MERS","url":"https://example.org/a"}\n'
    )

    result = process_toc(toc, {7: {"Dengue"}, 8: {"MERS"}}, RULES, NOW)

    assert result.language_filtered_candidates == 1
    assert len(result.articles) == 1
    assert result.articles[0].canonical_url == "https://example.org/a"
    assert result.articles[0].query_rule_id is None


def test_temporary_batch_files_are_cleaned_after_success_and_failure(tmp_path: Path) -> None:
    with temporary_batch_files(tmp_path) as paths:
        assert isinstance(paths, TemporaryBatchFiles)
        paths.ngram.write_bytes(b"ngram")
        paths.toc.write_bytes(b"toc")
        directory = paths.directory

    assert not directory.exists()

    with pytest.raises(RuntimeError), temporary_batch_files(tmp_path) as paths:
        paths.ngram.write_bytes(b"ngram")
        raise RuntimeError("stop")
    assert not paths.directory.exists()


class FakeClient:
    def __init__(self, outcomes: dict[datetime, str | Exception]) -> None:
        self.outcomes = outcomes
        self.downloaded: list[str] = []

    def inventory(
        self, start: datetime, end: datetime, *, max_batches: int
    ) -> tuple[NgramBatch, ...]:
        return tuple(
            NgramBatch(
                timestamp=timestamp,
                ngram_url=f"{timestamp.isoformat()}::ngram",
                toc_url=f"{timestamp.isoformat()}::toc",
            )
            for timestamp in sorted(self.outcomes)
            if start <= timestamp <= end
        )[:max_batches]

    def download(self, url: str, destination: Path, *, max_bytes: int | None = None) -> int:
        timestamp = datetime.fromisoformat(url.split("::", 1)[0])
        outcome = self.outcomes[timestamp]
        if isinstance(outcome, Exception):
            raise outcome
        raw_payload = outcome.encode() if url.endswith("::toc") else b"7\tdengue\t1\n"
        payload = gzip.compress(raw_payload)
        destination.write_bytes(payload)
        self.downloaded.append(url)
        return len(payload)


class FakeCursor:
    def __init__(self, cursor: datetime | None = None) -> None:
        self.cursor = cursor

    def get_cursor(self) -> datetime | None:
        return self.cursor

    def set_cursor(self, value: datetime) -> None:
        self.cursor = value


def test_discovery_reports_healthy_zero_and_advances_cursor(tmp_path: Path) -> None:
    first = NOW - timedelta(minutes=10)
    client = FakeClient(
        {
            first: '{"ID":7,"lang":"en","title":"Dengue","url":"https://example.org/a"}',
        }
    )
    cursor = FakeCursor()
    discovery = GdeltNgramDiscovery(client, cursor_store=cursor, temp_directory=tmp_path)

    result = discovery.discover_rules(RULES, TimeWindow(start=first, end=NOW))

    assert result.status is NgramProviderStatus.HEALTHY
    assert result.metrics.complete_pairs == 1
    assert result.metrics.unique_candidates == 1
    assert result.cursor_after == first
    assert cursor.cursor is None

    discovery.complete(result.cursor_after, success=True)
    assert cursor.cursor == first


def test_failed_batch_does_not_advance_cursor_and_exposes_partial_degradation(
    tmp_path: Path,
) -> None:
    first = NOW - timedelta(minutes=10)
    second = NOW - timedelta(minutes=5)
    client = FakeClient(
        {
            first: '{"ID":7,"lang":"en","title":"Dengue","url":"https://example.org/a"}',
            second: RuntimeError("download failed"),
        }
    )
    cursor = FakeCursor()
    discovery = GdeltNgramDiscovery(client, cursor_store=cursor, temp_directory=tmp_path)

    result = discovery.discover_rules(RULES, TimeWindow(start=first, end=NOW))

    assert result.status is NgramProviderStatus.PARTIAL
    assert result.metrics.batches_succeeded == 1
    assert result.metrics.batches_failed == 1
    assert result.cursor_after == first
    discovery.complete(result.cursor_after, success=True)
    assert cursor.cursor == first


def test_total_provider_failure_is_unavailable_and_does_not_advance(tmp_path: Path) -> None:
    first = NOW - timedelta(minutes=10)
    client = FakeClient({first: RuntimeError("download failed")})
    cursor = FakeCursor()
    discovery = GdeltNgramDiscovery(client, cursor_store=cursor, temp_directory=tmp_path)

    result = discovery.discover_rules(RULES, TimeWindow(start=first, end=NOW))

    assert result.status is NgramProviderStatus.UNAVAILABLE
    assert result.metrics.batches_attempted == 1
    assert result.metrics.batches_failed == 1
    discovery.complete(result.cursor_after, success=True)
    assert cursor.cursor is None


def test_cursor_initialization_and_bounded_catchup(tmp_path: Path) -> None:
    cursor = FakeCursor(NOW - timedelta(hours=12))
    client = FakeClient({})
    discovery = GdeltNgramDiscovery(
        client,
        cursor_store=cursor,
        max_catchup_minutes=60,
        temp_directory=tmp_path,
    )

    result = discovery.discover_rules(RULES, TimeWindow(start=NOW - timedelta(hours=24), end=NOW))

    assert result.metrics.catchup_minutes == 60
    assert result.metrics.cursor_before == NOW - timedelta(hours=12)
    assert result.metrics.cursor_after is None


def test_ngram_run_metrics_expose_requested_operational_fields() -> None:
    metrics = NgramRunMetrics()

    assert set(metrics.as_dict()) >= {
        "minutes_checked",
        "ngram_files_seen",
        "toc_files_seen",
        "complete_pairs",
        "batches_attempted",
        "batches_succeeded",
        "batches_failed",
        "bytes_downloaded",
        "documents_scanned",
        "raw_matched_docids",
        "language_filtered_candidates",
        "unique_candidates",
        "catchup_minutes",
        "cursor_before",
        "cursor_after",
    }


class BatchRepository:
    def __init__(self) -> None:
        self.added = []
        self.commits = 0

    def active_rules(self) -> tuple[QueryRule, ...]:
        return RULES

    def filter_rules(self) -> tuple[object, ...]:
        return ()

    def seen_urls(self, urls: tuple[str, ...]) -> frozenset[str]:
        return frozenset()

    def first_seen_at(self, canonical_url: str) -> datetime | None:
        return None

    def publisher_source_id(self, publisher: object):
        return uuid4()

    def add(self, signal: object, source_id: object) -> object:
        self.added.append(signal)
        return uuid4()

    def record_rejection(self, rejection: object) -> None:
        raise AssertionError("no rejection expected")

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        raise AssertionError("no rollback expected")


class BatchConnector:
    supports_batch_discovery = True

    def __init__(self, result) -> None:
        self.result = result
        self.completed = []

    def discover_rules(self, rules, window):
        return self.result

    def complete_discovery(self, cursor_after, *, success):
        self.completed.append((cursor_after, success))

    def defer(self, article, first_seen_at):
        from episignal_backend.ingestion.documents import DiscoveredSignal, Publisher

        return DiscoveredSignal(
            url=article.url,
            canonical_url=article.canonical_url,
            title=article.title,
            retrieved_at=first_seen_at,
            first_seen_at=first_seen_at,
            gdelt_seen_at=article.gdelt_seen_at,
            content_hash="a" * 64,
            publisher=Publisher(domain=article.domain, name=article.domain),
            processing_status=ProcessingStatus.FETCHED,
        )


def test_batch_discovery_feeds_normal_pipeline_candidates_and_completes_cursor() -> None:
    from episignal_backend.ingestion.documents import DiscoveredArticle
    from episignal_backend.ingestion.gdelt.ngram import NgramDiscoveryResult, NgramProviderStatus

    article = DiscoveredArticle(
        url="https://example.org/a",
        canonical_url="https://example.org/a",
        title="Dengue cases",
        domain="example.org",
        gdelt_seen_at=NOW,
        language="en",
    )
    result = NgramDiscoveryResult(
        candidates=(article,),
        status=NgramProviderStatus.HEALTHY,
        metrics=NgramRunMetrics(unique_candidates=1),
        cursor_after=NOW,
    )
    repository = BatchRepository()
    connector = BatchConnector(result)

    discovery = run_discovery(repository, connector, now=NOW)  # type: ignore[arg-type]

    assert discovery.stored == 1
    assert len(repository.added) == 1
    assert connector.completed == [(NOW, True)]
