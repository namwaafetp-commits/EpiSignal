"""Non-production benchmark for GDELT Web Legacy NGram discovery.

This script is intentionally outside the runtime package and is never called by
scheduled discovery. It discovers a bounded observation window, downloads one
complete batch at a time, retains only matched DOCIDs, joins those IDs to the
compressed TOC, and deletes temporary files before moving to the next batch.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter, sleep
from typing import Any, Literal, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from episignal_backend.ingestion.urls import canonicalize_url
from episignal_backend.seeds import load_query_rules

BASE_URL = "https://data.gdeltproject.org/gdeltv5/weblegacy/ngrams"
MAX_BATCHES = 8
MAX_RECENT_HOURS = 6.0
MAX_EXHAUSTIVE_HOURS = 2.0
SAFE_LAG_MINUTES = 5
MATCH_CACHE_SIZE = 16_384
PROFILE_FIXTURE_ROWS = 100_000
VPS_BASELINE_GB_PER_MONTH = 31.0
TOKEN_RE = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)
MatcherName = Literal["legacy", "optimized"]


@dataclass(frozen=True)
class BenchmarkRule:
    label: str
    phrase: str
    rule_group: str
    language: str = "en"
    _tokens: tuple[str, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_tokens", tokenize(self.phrase))

    @property
    def tokens(self) -> tuple[str, ...]:
        return self._tokens


@dataclass(frozen=True)
class RuleIndex:
    by_first_token: dict[str, tuple[BenchmarkRule, ...]]


@dataclass(frozen=True)
class NgramRow:
    docid: int
    quadgram: str
    count: int


@dataclass(frozen=True)
class Candidate:
    timestamp: str
    language: str
    title: str
    url: str
    rules: tuple[str, ...]

    @property
    def domain(self) -> str:
        return urlsplit(self.url).hostname or "(unknown)"


@dataclass(frozen=True)
class ScanProfile:
    matcher: MatcherName
    uncompressed_bytes_scanned: int
    rows_scanned: int
    quadgrams_scanned: int
    tokenization_seconds: float
    matching_seconds: float
    gzip_decompression_seconds: float
    total_seconds: float
    unique_quadgrams: int
    cache_hits: int


@dataclass(frozen=True)
class ScanResult:
    matches: dict[int, set[str]]
    profile: ScanProfile


@dataclass(frozen=True)
class MatcherComparison:
    fixture_rows: int
    fixture_uncompressed_bytes: int
    old_scan_seconds: float
    new_scan_seconds: float
    speedup: float
    match_sets_identical: bool


@dataclass(frozen=True)
class TocResolution:
    documents_represented: int
    raw_candidates: tuple[Candidate, ...]
    english_candidates: tuple[Candidate, ...]
    raw_lexical_matched_docids: int
    english_matched_docids: int


@dataclass(frozen=True)
class BatchInventory:
    window_start: datetime
    window_end: datetime
    minutes_checked: int
    ngram_files_present: int
    toc_files_present: int
    complete_timestamps: tuple[datetime, ...]
    exhaustive: bool


@dataclass(frozen=True)
class BatchMeasurement:
    timestamp: datetime
    ngram_compressed_bytes: int
    toc_compressed_bytes: int
    ngram_download_seconds: float
    toc_download_seconds: float
    scan_seconds: float
    toc_processing_seconds: float
    uncompressed_bytes_scanned: int
    rows_scanned: int
    quadgrams_scanned: int
    tokenization_seconds: float
    matching_seconds: float
    gzip_decompression_seconds: float
    documents_represented: int
    raw_lexical_matched_docids: int
    english_matched_docids: int
    raw_unique_candidate_urls: int
    english_unique_candidate_urls: int
    peak_rss_bytes: int | None
    peak_temp_disk_bytes: int

    @property
    def total_download_bytes(self) -> int:
        return self.ngram_compressed_bytes + self.toc_compressed_bytes


@dataclass(frozen=True)
class AggregateMetrics:
    batches_processed: int
    total_ngram_compressed_bytes: int
    total_toc_compressed_bytes: int
    total_download_bytes: int
    candidate_urls: int
    unique_candidate_urls: int
    documents_represented: int
    raw_lexical_matched_docids: int
    english_matched_docids: int
    elapsed_seconds: float
    download_seconds: float
    scan_seconds: float
    toc_processing_seconds: float
    uncompressed_bytes_scanned: int
    rows_scanned: int
    quadgrams_scanned: int
    tokenization_seconds: float
    matching_seconds: float
    gzip_decompression_seconds: float
    peak_rss_bytes: int | None
    peak_temp_disk_bytes: int
    bandwidth_observed: bool
    observation_hours: float
    mb_per_hour: float | None
    gb_per_day: float | None
    gb_per_month: float | None
    projected_vps_total_gb_month: float | None
    ngram_processing_minutes_per_hour: float | None


@dataclass(frozen=True)
class BenchmarkResult:
    started_at: datetime
    finished_at: datetime
    recent_hours: float
    inventory: BatchInventory
    measurements: tuple[BatchMeasurement, ...]
    raw_candidates: tuple[Candidate, ...]
    candidates: tuple[Candidate, ...]
    matcher_comparison: MatcherComparison
    skipped_timestamps: tuple[datetime, ...] = ()

    @property
    def elapsed_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def totals(self) -> AggregateMetrics:
        return aggregate_metrics(
            self.measurements,
            observation_hours=self.recent_hours,
            bandwidth_observed=(
                self.inventory.exhaustive
                and bool(self.inventory.complete_timestamps)
                and not self.skipped_timestamps
            ),
            elapsed_seconds=self.elapsed_seconds,
            unique_candidate_urls=len(self.candidates),
        )


@dataclass(frozen=True)
class TemporaryBatchFiles:
    directory: Path
    ngram: Path
    toc: Path


@contextmanager
def temporary_batch_files(base_dir: Path | None = None) -> Iterator[TemporaryBatchFiles]:
    """Create one disposable batch directory and always remove it on exit."""

    with tempfile.TemporaryDirectory(dir=base_dir, prefix="episignal-gdelt-") as raw_dir:
        directory = Path(raw_dir)
        yield TemporaryBatchFiles(
            directory=directory,
            ngram=directory / "batch.ngrams.txt.gz",
            toc=directory / "batch.toc.json.gz",
        )


def tokenize(value: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold() for match in TOKEN_RE.finditer(value))


def _parse_ngram_line(raw_line: str, line_number: int) -> NgramRow | None:
    line = raw_line.rstrip("\r\n")
    if not line:
        return None
    columns = line.split("\t")
    if len(columns) != 3:
        raise ValueError(f"NGram line {line_number} has {len(columns)} columns, expected 3")
    try:
        return NgramRow(docid=int(columns[0]), quadgram=columns[1], count=int(columns[2]))
    except ValueError as exc:
        raise ValueError(f"NGram line {line_number} has invalid numeric field") from exc


def parse_ngram_rows(handle: TextIO) -> Iterator[NgramRow]:
    for line_number, raw_line in enumerate(handle, start=1):
        row = _parse_ngram_line(raw_line, line_number)
        if row is not None:
            yield row


def build_rule_index(rules: Iterable[BenchmarkRule]) -> RuleIndex:
    by_first_token: dict[str, list[BenchmarkRule]] = {}
    for rule in rules:
        if rule.tokens:
            by_first_token.setdefault(rule.tokens[0], []).append(rule)
    return RuleIndex({key: tuple(value) for key, value in by_first_token.items()})


def _match_rule_index(words: tuple[str, ...], rule_index: RuleIndex) -> tuple[str, ...]:
    matched: list[str] = []
    for index, word in enumerate(words):
        for rule in rule_index.by_first_token.get(word, ()):
            phrase = rule.tokens
            if words[index : index + len(phrase)] == phrase:
                matched.append(rule.label)
    return tuple(sorted(set(matched)))


def match_rules(quadgram: str, rules: Iterable[BenchmarkRule]) -> tuple[str, ...]:
    """Return exact token-boundary matches using the optimized matcher."""

    rule_index = build_rule_index(rules)
    return _match_rule_index(tokenize(quadgram), rule_index)


def _scan_ngram(handle: TextIO, rules: Iterable[BenchmarkRule], matcher: MatcherName) -> ScanResult:
    rule_index = build_rule_index(rules)
    cache: dict[str, tuple[str, ...]] = {}
    matches: dict[int, set[str]] = {}
    bytes_scanned = 0
    rows_scanned = 0
    quadgrams_scanned = 0
    tokenization_seconds = 0.0
    matching_seconds = 0.0
    gzip_seconds = 0.0
    cache_hits = 0
    started = perf_counter()
    iterator = iter(handle)

    while True:
        read_started = perf_counter()
        try:
            raw_line = next(iterator)
        except StopIteration:
            gzip_seconds += perf_counter() - read_started
            break
        gzip_seconds += perf_counter() - read_started
        bytes_scanned += len(raw_line.encode("utf-8"))
        row = _parse_ngram_line(raw_line, rows_scanned + 1)
        if row is None:
            continue
        rows_scanned += 1
        quadgrams_scanned += 1

        if matcher == "optimized" and row.quadgram in cache:
            labels = cache[row.quadgram]
            cache_hits += 1
        else:
            token_started = perf_counter()
            words = tokenize(row.quadgram)
            tokenization_seconds += perf_counter() - token_started
            matching_started = perf_counter()
            labels = _match_rule_index(words, rule_index)
            matching_seconds += perf_counter() - matching_started
            if matcher == "optimized" and len(cache) < MATCH_CACHE_SIZE:
                cache[row.quadgram] = labels
        if labels:
            matches.setdefault(row.docid, set()).update(labels)

    profile = ScanProfile(
        matcher=matcher,
        uncompressed_bytes_scanned=bytes_scanned,
        rows_scanned=rows_scanned,
        quadgrams_scanned=quadgrams_scanned,
        tokenization_seconds=tokenization_seconds,
        matching_seconds=matching_seconds,
        gzip_decompression_seconds=gzip_seconds,
        total_seconds=perf_counter() - started,
        unique_quadgrams=len(cache),
        cache_hits=cache_hits,
    )
    return ScanResult(matches=matches, profile=profile)


def scan_ngram(handle: TextIO, rules: Iterable[BenchmarkRule]) -> dict[int, set[str]]:
    return _scan_ngram(handle, rules, "optimized").matches


def scan_ngram_legacy(handle: TextIO, rules: Iterable[BenchmarkRule]) -> dict[int, set[str]]:
    """Profile the pre-cache matcher for an apples-to-apples local comparison."""

    return _scan_ngram(handle, rules, "legacy").matches


def profile_ngram(
    handle: TextIO,
    rules: Iterable[BenchmarkRule],
    *,
    matcher: MatcherName = "optimized",
) -> ScanResult:
    return _scan_ngram(handle, rules, matcher)


def _profile_fixture(rules: tuple[BenchmarkRule, ...], rows: int) -> str:
    phrases = [rule.phrase for rule in rules] or ["ordinary weather today"]
    lines = []
    for index in range(rows):
        phrase = phrases[index % len(phrases)] if index % 5 else "ordinary weather today"
        lines.append(f"{index}\t{phrase}\t1\n")
    return "".join(lines)


def compare_matchers(
    rules: tuple[BenchmarkRule, ...], *, rows: int = PROFILE_FIXTURE_ROWS
) -> MatcherComparison:
    fixture = _profile_fixture(rules, rows)
    old = profile_ngram(io.StringIO(fixture), rules, matcher="legacy")
    new = profile_ngram(io.StringIO(fixture), rules, matcher="optimized")
    old_seconds = old.profile.total_seconds
    new_seconds = new.profile.total_seconds
    return MatcherComparison(
        fixture_rows=rows,
        fixture_uncompressed_bytes=len(fixture.encode("utf-8")),
        old_scan_seconds=old_seconds,
        new_scan_seconds=new_seconds,
        speedup=(old_seconds / new_seconds) if new_seconds else 0.0,
        match_sets_identical=old.matches == new.matches,
    )


def _record_candidate(
    record: dict[str, Any],
    labels: set[str],
    batch_timestamp: datetime,
) -> Candidate:
    date = record.get("date")
    timestamp = str(date) if date else batch_timestamp.isoformat().replace("+00:00", "Z")
    language = str(record.get("lang") or "unknown").strip().casefold()
    return Candidate(
        timestamp=timestamp,
        language=language,
        title=str(record.get("title") or "(untitled)"),
        url=str(record["url"]),
        rules=tuple(sorted(labels)),
    )


def _merge_candidate(target: dict[str, Candidate], candidate: Candidate) -> None:
    key = canonicalize_url(candidate.url)
    existing = target.get(key)
    if existing is None:
        target[key] = candidate
        return
    target[key] = Candidate(
        timestamp=existing.timestamp,
        language=existing.language,
        title=existing.title,
        url=existing.url,
        rules=tuple(sorted(set(existing.rules) | set(candidate.rules))),
    )


def process_toc(
    handle: TextIO,
    matched_docids: dict[int, set[str]],
    batch_timestamp: datetime,
    *,
    production_language: str = "en",
) -> TocResolution:
    """Join matched DOCIDs to TOC records before and after the language guard."""

    documents_represented = 0
    raw_by_url: dict[str, Candidate] = {}
    english_by_url: dict[str, Candidate] = {}
    raw_docids: set[int] = set()
    english_docids: set[int] = set()
    for line_number, raw_line in enumerate(handle, start=1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"TOC line {line_number} is not valid JSON") from exc
        if not isinstance(record, dict) or "ID" not in record:
            raise ValueError(f"TOC line {line_number} lacks ID")
        documents_represented += 1
        try:
            docid = int(record["ID"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"TOC line {line_number} has invalid ID") from exc
        labels = matched_docids.get(docid)
        if not labels or not record.get("url"):
            continue
        raw_docids.add(docid)
        candidate = _record_candidate(record, labels, batch_timestamp)
        _merge_candidate(raw_by_url, candidate)
        if candidate.language != production_language.casefold():
            continue
        english_docids.add(docid)
        _merge_candidate(english_by_url, candidate)
    return TocResolution(
        documents_represented=documents_represented,
        raw_candidates=tuple(raw_by_url.values()),
        english_candidates=tuple(english_by_url.values()),
        raw_lexical_matched_docids=len(raw_docids),
        english_matched_docids=len(english_docids),
    )


def _url_for(timestamp: datetime, suffix: str) -> str:
    stamp = timestamp.astimezone(UTC).strftime("%Y%m%d%H%M00")
    return f"{BASE_URL}/{stamp}.{suffix}"


def _request(url: str, timeout_seconds: float, method: str = "GET") -> Any:
    return urlopen(
        Request(url, method=method, headers={"User-Agent": "EpiSignal-NGram-Benchmark/1.0"}),
        timeout=timeout_seconds,
    )


def is_available(url: str, timeout_seconds: float) -> bool:
    for attempt in range(2):
        try:
            with _request(url, timeout_seconds, method="HEAD") as response:
                return 200 <= response.status < 400
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504}:
                return False
        except (URLError, TimeoutError, OSError):
            pass
        if attempt == 0:
            sleep(0.2)
    return False


def _window_bounds(now: datetime, recent_hours: float) -> tuple[datetime, datetime]:
    end = (now.astimezone(UTC) - timedelta(minutes=SAFE_LAG_MINUTES)).replace(
        second=0, microsecond=0
    )
    return end - timedelta(hours=recent_hours), end


def _probe_file(item: tuple[datetime, str, float]) -> tuple[datetime, str, bool]:
    timestamp, suffix, timeout_seconds = item
    return timestamp, suffix, is_available(_url_for(timestamp, suffix), timeout_seconds)


def discover_batch_inventory(
    *,
    now: datetime,
    recent_hours: float,
    max_batches: int,
    timeout_seconds: float,
    all_batches: bool = False,
) -> BatchInventory:
    validate_limits(recent_hours, max_batches, timeout_seconds, all_batches=all_batches)
    start, end = _window_bounds(now, recent_hours)
    ngram_files_present = 0
    toc_files_present = 0
    complete: list[datetime] = []
    minutes_checked = 0
    cursor = end
    if all_batches:
        probe_timeout_seconds = min(timeout_seconds, 10.0)
        cursors = tuple(
            start + timedelta(minutes=offset) for offset in range(int(recent_hours * 60) + 1)
        )
        probes = [
            (timestamp, suffix, probe_timeout_seconds)
            for timestamp in cursors
            for suffix in ("ngrams.txt.gz", "toc.json.gz")
        ]
        with ThreadPoolExecutor(max_workers=min(8, len(probes))) as executor:
            results = tuple(executor.map(_probe_file, probes))
        availability = {(timestamp, suffix): present for timestamp, suffix, present in results}
        ngram_files_present = sum(
            availability[(timestamp, "ngrams.txt.gz")] for timestamp in cursors
        )
        toc_files_present = sum(availability[(timestamp, "toc.json.gz")] for timestamp in cursors)
        complete = [
            timestamp
            for timestamp in reversed(cursors)
            if availability[(timestamp, "ngrams.txt.gz")]
            and availability[(timestamp, "toc.json.gz")]
        ]
        return BatchInventory(
            window_start=start,
            window_end=end,
            minutes_checked=len(cursors),
            ngram_files_present=ngram_files_present,
            toc_files_present=toc_files_present,
            complete_timestamps=tuple(complete),
            exhaustive=True,
        )
    while cursor >= start:
        minutes_checked += 1
        ngram_present = is_available(_url_for(cursor, "ngrams.txt.gz"), timeout_seconds)
        toc_present = is_available(_url_for(cursor, "toc.json.gz"), timeout_seconds)
        ngram_files_present += int(ngram_present)
        toc_files_present += int(toc_present)
        if ngram_present and toc_present:
            complete.append(cursor)
            if not all_batches and len(complete) >= max_batches:
                break
        cursor -= timedelta(minutes=1)
    return BatchInventory(
        window_start=start,
        window_end=end,
        minutes_checked=minutes_checked,
        ngram_files_present=ngram_files_present,
        toc_files_present=toc_files_present,
        complete_timestamps=tuple(complete),
        exhaustive=all_batches,
    )


def discover_batch_timestamps(
    *,
    now: datetime,
    recent_hours: float,
    max_batches: int,
    timeout_seconds: float,
) -> tuple[datetime, ...]:
    """Compatibility wrapper for bounded, non-exhaustive discovery tests."""

    return discover_batch_inventory(
        now=now,
        recent_hours=recent_hours,
        max_batches=max_batches,
        timeout_seconds=timeout_seconds,
    ).complete_timestamps


def download_file(url: str, destination: Path, timeout_seconds: float) -> tuple[int, float]:
    started = perf_counter()
    written = 0
    with _request(url, timeout_seconds) as response, destination.open("wb") as handle:
        while chunk := response.read(1024 * 1024):
            handle.write(chunk)
            written += len(chunk)
    return written, perf_counter() - started


def peak_rss_bytes() -> int | None:
    if sys.platform == "win32":
        try:
            import ctypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_size_t),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
            get_process_memory_info.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ProcessMemoryCounters),
                ctypes.c_ulong,
            ]
            get_process_memory_info.restype = ctypes.c_bool
            process = ctypes.windll.kernel32.GetCurrentProcess()
            if not get_process_memory_info(process, ctypes.byref(counters), counters.cb):
                return None
            return int(counters.PeakWorkingSetSize)
        except (AttributeError, ImportError, OSError):
            return None
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value * (1024 if sys.platform != "darwin" else 1))
    except (ImportError, AttributeError, OSError):
        return None


def validate_limits(
    recent_hours: float,
    max_batches: int,
    timeout_seconds: float,
    *,
    all_batches: bool = False,
) -> None:
    if not 0 < recent_hours <= MAX_RECENT_HOURS:
        raise ValueError(f"recent-hours must be between 0 and {MAX_RECENT_HOURS:g}")
    if all_batches and recent_hours > MAX_EXHAUSTIVE_HOURS:
        raise ValueError(f"all-batches supports at most {MAX_EXHAUSTIVE_HOURS:g} hours")
    if not 0 < max_batches <= MAX_BATCHES:
        raise ValueError(f"max-batches must be between 1 and {MAX_BATCHES}")
    if not 0 < timeout_seconds <= 120:
        raise ValueError("timeout-seconds must be between 0 and 120")


def run_benchmark(
    *,
    recent_hours: float = 2.0,
    max_batches: int = MAX_BATCHES,
    timeout_seconds: float = 30.0,
    all_batches: bool = False,
    now: datetime | None = None,
    output_directory: Path | None = None,
) -> BenchmarkResult:
    validate_limits(recent_hours, max_batches, timeout_seconds, all_batches=all_batches)
    started_at = datetime.now(UTC)
    scan_now = now or started_at
    rules = tuple(
        BenchmarkRule(
            label=rule.label,
            phrase=rule.query.strip('"'),
            rule_group=rule.rule_group,
            language=rule.language,
        )
        for rule in load_query_rules()
        if rule.active and rule.language == "en"
    )
    inventory = discover_batch_inventory(
        now=scan_now,
        recent_hours=recent_hours,
        max_batches=max_batches,
        timeout_seconds=timeout_seconds,
        all_batches=all_batches,
    )
    measurements: list[BatchMeasurement] = []
    raw_candidates_by_url: dict[str, Candidate] = {}
    candidates_by_url: dict[str, Candidate] = {}
    skipped: list[datetime] = []
    for timestamp in inventory.complete_timestamps:
        try:
            measurement, raw_candidates, candidates = process_batch(
                timestamp,
                rules,
                timeout_seconds=timeout_seconds,
                output_directory=output_directory,
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"Skipping {timestamp.isoformat()}: {exc}", file=sys.stderr)
            skipped.append(timestamp)
            continue
        measurements.append(measurement)
        for candidate in raw_candidates:
            _merge_candidate(raw_candidates_by_url, candidate)
        for candidate in candidates:
            _merge_candidate(candidates_by_url, candidate)
    finished_at = datetime.now(UTC)
    return BenchmarkResult(
        started_at=started_at,
        finished_at=finished_at,
        recent_hours=recent_hours,
        inventory=inventory,
        measurements=tuple(measurements),
        raw_candidates=tuple(raw_candidates_by_url.values()),
        candidates=tuple(candidates_by_url.values()),
        matcher_comparison=compare_matchers(rules),
        skipped_timestamps=tuple(skipped),
    )


def process_batch(
    timestamp: datetime,
    rules: tuple[BenchmarkRule, ...],
    *,
    timeout_seconds: float,
    output_directory: Path | None,
) -> tuple[BatchMeasurement, tuple[Candidate, ...], tuple[Candidate, ...]]:
    with temporary_batch_files(output_directory) as paths:
        ngram_bytes, ngram_download_seconds = download_file(
            _url_for(timestamp, "ngrams.txt.gz"), paths.ngram, timeout_seconds
        )
        with gzip.open(paths.ngram, "rt", encoding="utf-8", errors="replace") as handle:
            scan_result = profile_ngram(handle, rules)
        paths.ngram.unlink()

        toc_bytes, toc_download_seconds = download_file(
            _url_for(timestamp, "toc.json.gz"), paths.toc, timeout_seconds
        )
        toc_started = perf_counter()
        with gzip.open(paths.toc, "rt", encoding="utf-8", errors="replace") as handle:
            resolution = process_toc(handle, scan_result.matches, timestamp)
        toc_processing_seconds = perf_counter() - toc_started
        peak_temp_disk_bytes = max(ngram_bytes, toc_bytes)
        measurement = BatchMeasurement(
            timestamp=timestamp,
            ngram_compressed_bytes=ngram_bytes,
            toc_compressed_bytes=toc_bytes,
            ngram_download_seconds=ngram_download_seconds,
            toc_download_seconds=toc_download_seconds,
            scan_seconds=scan_result.profile.total_seconds,
            toc_processing_seconds=toc_processing_seconds,
            uncompressed_bytes_scanned=scan_result.profile.uncompressed_bytes_scanned,
            rows_scanned=scan_result.profile.rows_scanned,
            quadgrams_scanned=scan_result.profile.quadgrams_scanned,
            tokenization_seconds=scan_result.profile.tokenization_seconds,
            matching_seconds=scan_result.profile.matching_seconds,
            gzip_decompression_seconds=scan_result.profile.gzip_decompression_seconds,
            documents_represented=resolution.documents_represented,
            raw_lexical_matched_docids=resolution.raw_lexical_matched_docids,
            english_matched_docids=resolution.english_matched_docids,
            raw_unique_candidate_urls=len(resolution.raw_candidates),
            english_unique_candidate_urls=len(resolution.english_candidates),
            peak_rss_bytes=peak_rss_bytes(),
            peak_temp_disk_bytes=peak_temp_disk_bytes,
        )
        return measurement, resolution.raw_candidates, resolution.english_candidates


def aggregate_metrics(
    measurements: Iterable[BatchMeasurement],
    *,
    observation_hours: float,
    bandwidth_observed: bool = True,
    elapsed_seconds: float | None = None,
    unique_candidate_urls: int | None = None,
) -> AggregateMetrics:
    rows = tuple(measurements)
    total_ngram_bytes = sum(row.ngram_compressed_bytes for row in rows)
    total_toc_bytes = sum(row.toc_compressed_bytes for row in rows)
    total_download_bytes = total_ngram_bytes + total_toc_bytes
    download_seconds = sum(row.ngram_download_seconds + row.toc_download_seconds for row in rows)
    scan_seconds = sum(row.scan_seconds for row in rows)
    mb_per_hour = (
        total_download_bytes / 1_000_000 / observation_hours
        if bandwidth_observed and observation_hours
        else None
    )
    gb_per_day = mb_per_hour * 24 / 1_000 if mb_per_hour is not None else None
    gb_per_month = gb_per_day * 30 if gb_per_day is not None else None
    projected_vps = VPS_BASELINE_GB_PER_MONTH + gb_per_month if gb_per_month is not None else None
    rss_values = [row.peak_rss_bytes for row in rows if row.peak_rss_bytes is not None]
    return AggregateMetrics(
        batches_processed=len(rows),
        total_ngram_compressed_bytes=total_ngram_bytes,
        total_toc_compressed_bytes=total_toc_bytes,
        total_download_bytes=total_download_bytes,
        candidate_urls=sum(row.english_unique_candidate_urls for row in rows),
        unique_candidate_urls=(
            unique_candidate_urls
            if unique_candidate_urls is not None
            else sum(row.english_unique_candidate_urls for row in rows)
        ),
        documents_represented=sum(row.documents_represented for row in rows),
        raw_lexical_matched_docids=sum(row.raw_lexical_matched_docids for row in rows),
        english_matched_docids=sum(row.english_matched_docids for row in rows),
        elapsed_seconds=elapsed_seconds or 0.0,
        download_seconds=download_seconds,
        scan_seconds=scan_seconds,
        toc_processing_seconds=sum(row.toc_processing_seconds for row in rows),
        uncompressed_bytes_scanned=sum(row.uncompressed_bytes_scanned for row in rows),
        rows_scanned=sum(row.rows_scanned for row in rows),
        quadgrams_scanned=sum(row.quadgrams_scanned for row in rows),
        tokenization_seconds=sum(row.tokenization_seconds for row in rows),
        matching_seconds=sum(row.matching_seconds for row in rows),
        gzip_decompression_seconds=sum(row.gzip_decompression_seconds for row in rows),
        peak_rss_bytes=max(rss_values) if rss_values else None,
        peak_temp_disk_bytes=max((row.peak_temp_disk_bytes for row in rows), default=0),
        bandwidth_observed=bandwidth_observed,
        observation_hours=observation_hours,
        mb_per_hour=mb_per_hour,
        gb_per_day=gb_per_day,
        gb_per_month=gb_per_month,
        projected_vps_total_gb_month=projected_vps,
        ngram_processing_minutes_per_hour=(scan_seconds / 60 / observation_hours)
        if observation_hours
        else None,
    )


def _mb(value: int) -> float:
    return value / 1_000_000


def _seconds(value: float) -> str:
    return f"{value:.2f}s"


def _optional(value: float | None, suffix: str = "") -> str:
    return "unavailable" if value is None else f"{value:.3f}{suffix}"


def _top_lines(counter: Counter[str], limit: int = 10) -> str:
    return "\n".join(f"  {name}: {count}" for name, count in counter.most_common(limit)) or "  none"


def _classify_cpu(minutes_per_hour: float | None, *, measured: bool) -> str:
    if not measured or minutes_per_hour is None:
        return "YELLOW"
    if minutes_per_hour <= 5:
        return "GREEN"
    if minutes_per_hour <= 15:
        return "YELLOW"
    return "RED"


def format_report(result: BenchmarkResult, *, example_limit: int = 30) -> str:
    totals = result.totals
    rule_counts: Counter[str] = Counter()
    language_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    for candidate in result.candidates:
        rule_counts.update(candidate.rules)
        language_counts.update([candidate.language])
        domain_counts.update([candidate.domain])
    inventory = result.inventory
    ngram_scan_mb_per_second = (
        _mb(totals.total_ngram_compressed_bytes) / totals.scan_seconds
        if totals.scan_seconds
        else 0.0
    )
    uncompressed_mb_per_second = (
        _mb(totals.uncompressed_bytes_scanned) / totals.scan_seconds if totals.scan_seconds else 0.0
    )
    peak_ram_mb = _mb(totals.peak_rss_bytes) if totals.peak_rss_bytes is not None else None
    measured = bool(result.measurements)
    ram_status = (
        "GREEN" if measured and peak_ram_mb is not None and peak_ram_mb <= 256 else "YELLOW"
    )
    disk_status = "GREEN" if measured and _mb(totals.peak_temp_disk_bytes) <= 512 else "YELLOW"
    cpu_status = _classify_cpu(totals.ngram_processing_minutes_per_hour, measured=measured)
    bandwidth_status = (
        "GREEN"
        if totals.bandwidth_observed
        else "RED"
        if not inventory.complete_timestamps
        else "YELLOW"
    )
    lines = [
        "GDELT Web Legacy NGram benchmark (non-production)",
        f"Window start: {inventory.window_start.isoformat()}",
        f"Window end: {inventory.window_end.isoformat()}",
        f"Observation mode: {'exhaustive' if inventory.exhaustive else 'capped sample'}",
        f"Minutes checked: {inventory.minutes_checked}",
        f"NGram files present: {inventory.ngram_files_present}",
        f"TOC files present: {inventory.toc_files_present}",
        f"Complete batch pairs: {len(inventory.complete_timestamps)}",
        "Complete pair timestamps: "
        + (
            ", ".join(timestamp.isoformat() for timestamp in inventory.complete_timestamps)
            if inventory.complete_timestamps
            else "none"
        ),
        f"Batches processed: {totals.batches_processed}",
        f"Batches skipped after discovery: {len(result.skipped_timestamps)}",
        "",
        "Bandwidth:",
        f"  NGram compressed MB: {_mb(totals.total_ngram_compressed_bytes):.3f}",
        f"  TOC compressed MB: {_mb(totals.total_toc_compressed_bytes):.3f}",
        f"  Total download MB: {_mb(totals.total_download_bytes):.3f}",
        f"  Actual complete-window bandwidth: {totals.bandwidth_observed}",
        f"  MB/hour: {_optional(totals.mb_per_hour)}",
        f"  GB/day: {_optional(totals.gb_per_day)}",
        f"  GB/30-day month: {_optional(totals.gb_per_month)}",
        f"  Projected VPS total GB/month: {_optional(totals.projected_vps_total_gb_month)}",
        "",
        "Yield:",
        f"  Documents represented: {totals.documents_represented}",
        f"  Raw lexical matched DOCIDs: {totals.raw_lexical_matched_docids}",
        f"  English-filtered matched DOCIDs: {totals.english_matched_docids}",
        f"  Raw unique candidate URLs: {len(result.raw_candidates)}",
        f"  English unique candidate URLs: {totals.unique_candidate_urls}",
        f"  MB per English candidate: "
        f"{_mb(totals.total_download_bytes) / totals.unique_candidate_urls:.3f}"
        if totals.unique_candidate_urls
        else "  MB per English candidate: unavailable",
        "",
        "NGram scan profile:",
        f"  Compressed NGram MB: {_mb(totals.total_ngram_compressed_bytes):.3f}",
        f"  Uncompressed bytes scanned: {totals.uncompressed_bytes_scanned}",
        f"  Rows scanned: {totals.rows_scanned}",
        f"  Quadgrams scanned: {totals.quadgrams_scanned}",
        f"  Tokenization time: {_seconds(totals.tokenization_seconds)}",
        f"  Matching time: {_seconds(totals.matching_seconds)}",
        f"  Gzip/decompression time: {_seconds(totals.gzip_decompression_seconds)}",
        f"  Total scan time: {_seconds(totals.scan_seconds)}",
        f"  Compressed MB/sec: {ngram_scan_mb_per_second:.3f}",
        f"  Uncompressed MB/sec: {uncompressed_mb_per_second:.3f}",
        "",
        "Matcher comparison (same local fixture):",
        f"  Fixture rows: {result.matcher_comparison.fixture_rows}",
        f"  Old matcher scan: {_seconds(result.matcher_comparison.old_scan_seconds)}",
        f"  New matcher scan: {_seconds(result.matcher_comparison.new_scan_seconds)}",
        f"  Speedup: {result.matcher_comparison.speedup:.2f}x",
        f"  Match sets identical: {result.matcher_comparison.match_sets_identical}",
        "",
        "Performance:",
        f"  Total elapsed: {_seconds(totals.elapsed_seconds)}",
        f"  Download: {_seconds(totals.download_seconds)}",
        f"  NGram scan: {_seconds(totals.scan_seconds)}",
        f"  TOC processing: {_seconds(totals.toc_processing_seconds)}",
        f"  NGram processing minutes/hour: {_optional(totals.ngram_processing_minutes_per_hour)}",
        f"  Peak RAM: {_optional(peak_ram_mb, ' MB')}",
        f"  Peak temp disk: {_mb(totals.peak_temp_disk_bytes):.3f} MB",
        "",
        "Feasibility:",
        f"  Bandwidth: {bandwidth_status}",
        f"  CPU/runtime: {cpu_status}",
        f"  RAM: {ram_status}",
        f"  Disk: {disk_status}",
        "  Candidate discovery: YELLOW (lexical discovery still needs downstream "
        "relevance filtering)",
        "  Recommendation: OPTIMIZE MORE",
        "",
        "Top matching rules:",
        _top_lines(rule_counts),
        "Top English candidate languages:",
        _top_lines(language_counts),
        "Top English candidate domains:",
        _top_lines(domain_counts),
        "",
        f"Safe English candidate examples (max {example_limit}; no article bodies):",
    ]
    if result.candidates:
        lines.extend(
            f"  {candidate.timestamp} | {candidate.language} | {', '.join(candidate.rules)} | "
            f"{candidate.title[:160]} | {candidate.url}"
            for candidate in result.candidates[:example_limit]
        )
    else:
        lines.append("  none")
    return "\n".join(lines) + "\n"


def write_report_safely(path: Path, report: str) -> bool:
    """Keep completed benchmark successful when optional mount is unwritable."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
    except OSError as exc:
        print(
            f"Could not write benchmark report ({type(exc).__name__}); report remains on stdout.",
            file=sys.stderr,
        )
        return False
    return True


def _bounded_hours(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not 0 < parsed <= MAX_RECENT_HOURS:
        raise argparse.ArgumentTypeError(f"must be between 0 and {MAX_RECENT_HOURS:g}")
    return parsed


def _bounded_batches(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 0 < parsed <= MAX_BATCHES:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_BATCHES}")
    return parsed


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("must include a timezone")
    return parsed.astimezone(UTC)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recent-hours", type=_bounded_hours, default=2.0)
    parser.add_argument("--max-batches", type=_bounded_batches, default=MAX_BATCHES)
    parser.add_argument(
        "--as-of",
        type=_aware_datetime,
        help="Use this UTC timestamp as the observation clock (useful for reproducibility)",
    )
    parser.add_argument(
        "--all-batches",
        action="store_true",
        help="Inspect every minute in the bounded window and process every complete pair",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path, help="Also write the safe text report to this path")
    arguments = parser.parse_args()
    try:
        result = run_benchmark(
            recent_hours=arguments.recent_hours,
            max_batches=arguments.max_batches,
            timeout_seconds=arguments.timeout_seconds,
            all_batches=arguments.all_batches,
            now=arguments.as_of,
            output_directory=None,
        )
    except ValueError as exc:
        parser.error(str(exc))
    report = format_report(result)
    print(report, end="")
    if arguments.output:
        write_report_safely(arguments.output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
