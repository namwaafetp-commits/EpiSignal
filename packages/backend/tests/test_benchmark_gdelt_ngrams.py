from __future__ import annotations

import gzip
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.benchmark_gdelt_ngrams import (  # noqa: E402
    BatchMeasurement,
    BenchmarkRule,
    NgramRow,
    aggregate_metrics,
    discover_batch_inventory,
    discover_batch_timestamps,
    match_rules,
    parse_ngram_rows,
    process_toc,
    scan_ngram,
    scan_ngram_legacy,
    temporary_batch_files,
)

RULES = (
    BenchmarkRule(label="MERS", phrase="mers", rule_group="known_disease"),
    BenchmarkRule(label="Dengue", phrase="dengue", rule_group="known_disease"),
    BenchmarkRule(
        label="Avian influenza",
        phrase="avian influenza",
        rule_group="known_disease",
    ),
)
NOW = datetime(2026, 9, 10, 2, 0, tzinfo=UTC)


def measurement(
    *,
    timestamp: datetime = datetime(2026, 9, 10, 0, 0, tzinfo=UTC),
    ngram_bytes: int = 1_000_000,
    toc_bytes: int = 500_000,
    raw_docids: int = 2,
    english_docids: int = 1,
    english_urls: int = 1,
) -> BatchMeasurement:
    return BatchMeasurement(
        timestamp=timestamp,
        ngram_compressed_bytes=ngram_bytes,
        toc_compressed_bytes=toc_bytes,
        ngram_download_seconds=2.0,
        toc_download_seconds=1.0,
        scan_seconds=4.0,
        toc_processing_seconds=1.0,
        uncompressed_bytes_scanned=4_000_000,
        rows_scanned=100,
        quadgrams_scanned=100,
        tokenization_seconds=1.0,
        matching_seconds=1.0,
        gzip_decompression_seconds=2.0,
        documents_represented=10,
        raw_lexical_matched_docids=raw_docids,
        english_matched_docids=english_docids,
        raw_unique_candidate_urls=2,
        english_unique_candidate_urls=english_urls,
        peak_rss_bytes=10_000_000,
        peak_temp_disk_bytes=max(ngram_bytes, toc_bytes),
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


def test_optimized_matcher_has_identical_docid_sets() -> None:
    payload = "".join(
        f"{index}\t{phrase}\t1\n"
        for index, phrase in enumerate(
            ("dengue outbreak", "ordinary weather", "avian influenza report", "MERS") * 20
        )
    )

    assert scan_ngram(io.StringIO(payload), RULES) == scan_ngram_legacy(io.StringIO(payload), RULES)


def test_profile_fixture_can_be_scanned_without_decompression_to_disk() -> None:
    payload = gzip.compress(b"9\tdengue outbreak now\t1\n")

    with gzip.open(io.BytesIO(payload), "rt", encoding="utf-8") as handle:
        assert scan_ngram(handle, RULES) == {9: {"Dengue"}}


def test_process_toc_reports_raw_and_english_filtered_matches() -> None:
    toc = io.StringIO(
        json.dumps(
            {
                "ID": 7,
                "date": "2026-09-10T01:00:00.000Z",
                "lang": "fr",
                "title": "Mers en France",
                "url": "https://example.org/mers-fr",
            }
        )
        + "\n"
        + json.dumps(
            {
                "ID": 8,
                "date": "2026-09-10T01:01:00.000Z",
                "lang": "en",
                "title": "MERS cases",
                "url": "https://example.org/mers-en",
            }
        )
        + "\n"
    )

    result = process_toc(toc, {7: {"MERS"}, 8: {"MERS"}}, NOW)

    assert result.raw_lexical_matched_docids == 2
    assert result.english_matched_docids == 1
    assert {candidate.language for candidate in result.raw_candidates} == {"fr", "en"}
    assert result.english_candidates[0].language == "en"


def test_process_toc_uses_production_url_canonicalization_and_deduplicates() -> None:
    records = [
        {
            "ID": 7,
            "date": "2026-09-10T01:00:00.000Z",
            "lang": "en",
            "title": "Dengue cases",
            "url": "HTTPS://Example.org/story/?utm_source=x&page=2#top",
        },
        {
            "ID": 8,
            "date": "2026-09-10T01:01:00.000Z",
            "lang": "en",
            "title": "Dengue cases again",
            "url": "https://example.org/story?page=2&utm_medium=email",
        },
    ]
    toc = io.StringIO("".join(json.dumps(record) + "\n" for record in records))

    result = process_toc(toc, {7: {"Dengue"}, 8: {"Dengue"}}, NOW)

    assert len(result.english_candidates) == 1
    assert result.english_candidates[0].rules == ("Dengue",)


def test_temporary_batch_files_are_deleted(tmp_path: Path) -> None:
    with temporary_batch_files(tmp_path) as paths:
        paths.ngram.write_bytes(b"ngram")
        paths.toc.write_bytes(b"toc")
        assert paths.ngram.exists()
        assert paths.toc.exists()

    assert paths.ngram.exists() is False
    assert paths.toc.exists() is False


def test_exhaustive_inventory_checks_every_minute_and_counts_each_file(monkeypatch) -> None:
    available = set()
    end = datetime(2026, 9, 10, 1, 55, tzinfo=UTC)
    first = end.replace(minute=54)
    second = end.replace(minute=35)
    from scripts import benchmark_gdelt_ngrams as benchmark

    available.update(
        {
            benchmark._url_for(first, "ngrams.txt.gz"),
            benchmark._url_for(first, "toc.json.gz"),
            benchmark._url_for(second, "ngrams.txt.gz"),
            benchmark._url_for(second, "toc.json.gz"),
            benchmark._url_for(second - benchmark.timedelta(minutes=1), "ngrams.txt.gz"),
        }
    )
    monkeypatch.setattr(
        benchmark,
        "is_available",
        lambda url, timeout_seconds: url in available,
    )

    inventory = discover_batch_inventory(
        now=NOW,
        recent_hours=2,
        max_batches=1,
        timeout_seconds=1,
        all_batches=True,
    )

    assert inventory.minutes_checked == 121
    assert inventory.ngram_files_present == 3
    assert inventory.toc_files_present == 2
    assert inventory.complete_timestamps == (first, second)


def test_capped_sample_cannot_produce_full_window_bandwidth() -> None:
    totals = aggregate_metrics(
        (measurement(),),
        observation_hours=2,
        bandwidth_observed=False,
    )

    assert totals.bandwidth_observed is False
    assert totals.mb_per_hour is None
    assert totals.gb_per_month is None


def test_complete_window_bandwidth_uses_observation_window() -> None:
    totals = aggregate_metrics(
        (measurement(), measurement(timestamp=datetime(2026, 9, 10, 1, 0, tzinfo=UTC))),
        observation_hours=2,
        bandwidth_observed=True,
    )

    assert totals.total_download_bytes == 3_000_000
    assert totals.mb_per_hour == 1.5
    assert totals.gb_per_day == 0.036
    assert totals.projected_vps_total_gb_month == 32.08


def test_missing_batch_is_not_reported_as_available(monkeypatch) -> None:
    from scripts import benchmark_gdelt_ngrams as benchmark

    monkeypatch.setattr(benchmark, "is_available", lambda url, timeout_seconds: False)

    found = discover_batch_timestamps(
        now=NOW,
        recent_hours=1,
        max_batches=1,
        timeout_seconds=1,
    )

    assert found == ()
