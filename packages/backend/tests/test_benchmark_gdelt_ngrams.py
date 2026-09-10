from __future__ import annotations

import gzip
import io
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.benchmark_gdelt_ngrams import (  # noqa: E402
    BatchMeasurement,
    BenchmarkRule,
    Candidate,
    NgramRow,
    aggregate_metrics,
    discover_batch_timestamps,
    match_rules,
    parse_ngram_rows,
    process_toc,
    scan_ngram,
    temporary_batch_files,
)

RULES = (
    BenchmarkRule(label="Dengue", phrase="dengue", rule_group="known_disease"),
    BenchmarkRule(label="Avian influenza", phrase="avian influenza", rule_group="known_disease"),
)


def test_parse_ngram_rows_reads_docid_quadgram_and_count() -> None:
    rows = list(parse_ngram_rows(io.StringIO("42\tDengue outbreak today\t3\n")))

    assert rows == [NgramRow(docid=42, quadgram="Dengue outbreak today", count=3)]


def test_match_rules_supports_single_word_and_multi_word_phrases_case_insensitively() -> None:
    assert match_rules("DENGUE cases reported", RULES) == ("Dengue",)
    assert match_rules("reports AVIAN INFLUENZA today", RULES) == ("Avian influenza",)


def test_match_rules_avoids_substring_false_positive() -> None:
    assert match_rules("indengue cases reported", RULES) == ()


def test_scan_ngram_collects_multiple_rules_for_same_docid() -> None:
    rows = io.StringIO(
        "7\tdengue cases reported\t1\n7\tavian influenza cases\t1\n8\tordinary weather\t4\n"
    )

    assert scan_ngram(rows, RULES) == {7: {"Dengue", "Avian influenza"}}


def test_process_toc_resolves_docids_and_deduplicates_urls() -> None:
    toc = io.StringIO(
        '{"ID":7,"date":"2026-09-10T01:00:00.000Z","lang":"en",'
        '"title":"Dengue cases","url":"https://example.org/dengue"}\n'
        '{"ID":8,"date":"2026-09-10T01:01:00.000Z","lang":"en",'
        '"title":"Other","url":"https://example.org/dengue"}\n'
    )

    result = process_toc(
        toc,
        {7: {"Dengue"}, 8: {"Avian influenza"}},
        datetime(2026, 9, 10, 1, 0, tzinfo=UTC),
    )

    assert result.documents_represented == 2
    assert result.candidates == (
        Candidate(
            timestamp="2026-09-10T01:00:00.000Z",
            language="en",
            title="Dengue cases",
            url="https://example.org/dengue",
            rules=("Avian influenza", "Dengue"),
        ),
    )


def test_temporary_batch_files_are_deleted(tmp_path: Path) -> None:
    ngram = tmp_path / "ngrams.gz"

    with temporary_batch_files(tmp_path) as paths:
        paths.ngram.write_bytes(b"ngram")
        paths.toc.write_bytes(b"toc")
        assert ngram.exists() is False
        assert paths.ngram.exists()
        assert paths.toc.exists()

    assert paths.ngram.exists() is False
    assert paths.toc.exists() is False


def test_aggregate_metrics_uses_observed_sample_window_for_extrapolation() -> None:
    metrics = (
        BatchMeasurement(
            timestamp=datetime(2026, 9, 10, 0, 0, tzinfo=UTC),
            ngram_compressed_bytes=1_000_000,
            toc_compressed_bytes=500_000,
            ngram_download_seconds=2.0,
            toc_download_seconds=1.0,
            scan_seconds=4.0,
            toc_processing_seconds=1.0,
            documents_represented=10,
            matched_docids=2,
            unique_candidate_urls=2,
            peak_rss_bytes=10_000_000,
            peak_temp_disk_bytes=1_000_000,
        ),
        BatchMeasurement(
            timestamp=datetime(2026, 9, 10, 1, 0, tzinfo=UTC),
            ngram_compressed_bytes=2_000_000,
            toc_compressed_bytes=500_000,
            ngram_download_seconds=3.0,
            toc_download_seconds=1.0,
            scan_seconds=5.0,
            toc_processing_seconds=2.0,
            documents_represented=20,
            matched_docids=3,
            unique_candidate_urls=3,
            peak_rss_bytes=12_000_000,
            peak_temp_disk_bytes=2_000_000,
        ),
    )

    totals = aggregate_metrics(metrics, recent_hours=2.0)

    assert totals.total_download_bytes == 4_000_000
    assert totals.estimated_mb_per_hour == 2.0
    assert totals.estimated_gb_per_day == 0.048
    assert totals.projected_vps_total_gb_month == 31 + 1.44


def test_fixture_gzip_payload_can_be_scanned_without_decompression_to_disk() -> None:
    payload = gzip.compress(b"9\tdengue outbreak now\t1\n")

    with gzip.open(io.BytesIO(payload), "rt", encoding="utf-8") as handle:
        assert scan_ngram(handle, RULES) == {9: {"Dengue"}}


def test_missing_batch_is_not_reported_as_available(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.benchmark_gdelt_ngrams.is_available",
        lambda url, timeout_seconds: False,
    )

    found = discover_batch_timestamps(
        now=datetime(2026, 9, 10, 2, 0, tzinfo=UTC),
        recent_hours=1,
        max_batches=1,
        timeout_seconds=1,
    )

    assert found == ()
