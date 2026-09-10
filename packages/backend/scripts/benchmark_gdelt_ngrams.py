"""Non-production benchmark for GDELT Web Legacy NGram discovery.

This script is intentionally outside the runtime package and is never called by
scheduled discovery. It downloads one compressed batch at a time, retains only
matched DOCIDs, joins those IDs to the compressed TOC, and deletes temporary
files before moving to the next batch.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from episignal_backend.seeds import load_query_rules

BASE_URL = "https://data.gdeltproject.org/gdeltv5/weblegacy/ngrams"
MAX_BATCHES = 8
MAX_RECENT_HOURS = 6.0
SAFE_LAG_MINUTES = 5
VPS_BASELINE_GB_PER_DAY = 1.05
VPS_BASELINE_GB_PER_MONTH = 31.0
TOKEN_RE = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)


@dataclass(frozen=True)
class BenchmarkRule:
    label: str
    phrase: str
    rule_group: str
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
class TocResolution:
    documents_represented: int
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True)
class BatchMeasurement:
    timestamp: datetime
    ngram_compressed_bytes: int
    toc_compressed_bytes: int
    ngram_download_seconds: float
    toc_download_seconds: float
    scan_seconds: float
    toc_processing_seconds: float
    documents_represented: int
    matched_docids: int
    unique_candidate_urls: int
    peak_rss_bytes: int | None
    peak_temp_disk_bytes: int

    @property
    def total_download_bytes(self) -> int:
        return self.ngram_compressed_bytes + self.toc_compressed_bytes


@dataclass(frozen=True)
class AggregateMetrics:
    batches_processed: int
    total_download_bytes: int
    candidate_urls: int
    unique_candidate_urls: int
    documents_represented: int
    matched_docids: int
    elapsed_seconds: float
    download_seconds: float
    scan_seconds: float
    toc_processing_seconds: float
    peak_rss_bytes: int | None
    peak_temp_disk_bytes: int
    estimated_mb_per_hour: float
    estimated_gb_per_day: float
    estimated_gb_per_month: float
    projected_vps_total_gb_month: float


@dataclass(frozen=True)
class BenchmarkResult:
    started_at: datetime
    finished_at: datetime
    recent_hours: float
    measurements: tuple[BatchMeasurement, ...]
    candidates: tuple[Candidate, ...]
    skipped_timestamps: tuple[datetime, ...] = ()

    @property
    def elapsed_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def totals(self) -> AggregateMetrics:
        return aggregate_metrics(
            self.measurements,
            recent_hours=self.recent_hours,
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


def parse_ngram_rows(handle: TextIO) -> Iterator[NgramRow]:
    for line_number, raw_line in enumerate(handle, start=1):
        line = raw_line.rstrip("\r\n")
        if not line:
            continue
        columns = line.split("\t")
        if len(columns) != 3:
            raise ValueError(f"NGram line {line_number} has {len(columns)} columns, expected 3")
        try:
            yield NgramRow(docid=int(columns[0]), quadgram=columns[1], count=int(columns[2]))
        except ValueError as exc:
            raise ValueError(f"NGram line {line_number} has invalid numeric field") from exc


def match_rules(quadgram: str, rules: Iterable[BenchmarkRule]) -> tuple[str, ...]:
    return _match_rule_index(tokenize(quadgram), build_rule_index(rules))


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


def scan_ngram(handle: TextIO, rules: Iterable[BenchmarkRule]) -> dict[int, set[str]]:
    matched: dict[int, set[str]] = {}
    rule_index = build_rule_index(rules)
    for row in parse_ngram_rows(handle):
        labels = _match_rule_index(tokenize(row.quadgram), rule_index)
        if labels:
            matched.setdefault(row.docid, set()).update(labels)
    return matched


def _canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit(
        (parts.scheme.casefold(), parts.netloc.casefold(), parts.path, parts.query, "")
    )


def _record_candidate(
    record: dict[str, Any],
    labels: set[str],
    batch_timestamp: datetime,
) -> Candidate:
    date = record.get("date")
    timestamp = str(date) if date else batch_timestamp.isoformat().replace("+00:00", "Z")
    return Candidate(
        timestamp=timestamp,
        language=str(record.get("lang") or "unknown"),
        title=str(record.get("title") or "(untitled)"),
        url=str(record["url"]),
        rules=tuple(sorted(labels)),
    )


def process_toc(
    handle: TextIO,
    matched_docids: dict[int, set[str]],
    batch_timestamp: datetime,
) -> TocResolution:
    """Join matched DOCIDs to newline-delimited TOC JSON records."""

    documents_represented = 0
    by_url: dict[str, Candidate] = {}
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
        candidate = _record_candidate(record, labels, batch_timestamp)
        key = _canonical_url(candidate.url)
        if key not in by_url:
            by_url[key] = candidate
        else:
            existing = by_url[key]
            by_url[key] = Candidate(
                timestamp=existing.timestamp,
                language=existing.language,
                title=existing.title,
                url=existing.url,
                rules=tuple(sorted(set(existing.rules) | set(candidate.rules))),
            )
    return TocResolution(documents_represented, tuple(by_url.values()))


def _url_for(timestamp: datetime, suffix: str) -> str:
    stamp = timestamp.astimezone(UTC).strftime("%Y%m%d%H%M00")
    return f"{BASE_URL}/{stamp}.{suffix}"


def _request(url: str, timeout_seconds: float, method: str = "GET") -> Any:
    return urlopen(
        Request(url, method=method, headers={"User-Agent": "EpiSignal-NGram-Benchmark/1.0"}),
        timeout=timeout_seconds,
    )


def is_available(url: str, timeout_seconds: float) -> bool:
    try:
        with _request(url, timeout_seconds, method="HEAD") as response:
            return 200 <= response.status < 400
    except (HTTPError, URLError, TimeoutError, OSError):
        return False


def discover_batch_timestamps(
    *,
    now: datetime,
    recent_hours: float,
    max_batches: int,
    timeout_seconds: float,
) -> tuple[datetime, ...]:
    validate_limits(recent_hours, max_batches, timeout_seconds)
    end = (now.astimezone(UTC) - timedelta(minutes=SAFE_LAG_MINUTES)).replace(
        second=0, microsecond=0
    )
    start = end - timedelta(hours=recent_hours)
    found: list[datetime] = []
    cursor = end
    while cursor >= start and len(found) < max_batches:
        ngram_url = _url_for(cursor, "ngrams.txt.gz")
        toc_url = _url_for(cursor, "toc.json.gz")
        if is_available(ngram_url, timeout_seconds) and is_available(toc_url, timeout_seconds):
            found.append(cursor)
        cursor -= timedelta(minutes=1)
    return tuple(found)


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


def validate_limits(recent_hours: float, max_batches: int, timeout_seconds: float) -> None:
    if not 0 < recent_hours <= MAX_RECENT_HOURS:
        raise ValueError(f"recent-hours must be between 0 and {MAX_RECENT_HOURS:g}")
    if not 0 < max_batches <= MAX_BATCHES:
        raise ValueError(f"max-batches must be between 1 and {MAX_BATCHES}")
    if not 0 < timeout_seconds <= 120:
        raise ValueError("timeout-seconds must be between 0 and 120")


def run_benchmark(
    *,
    recent_hours: float = 2.0,
    max_batches: int = MAX_BATCHES,
    timeout_seconds: float = 30.0,
    now: datetime | None = None,
    output_directory: Path | None = None,
) -> BenchmarkResult:
    validate_limits(recent_hours, max_batches, timeout_seconds)
    started_at = datetime.now(UTC)
    scan_now = now or started_at
    rules = tuple(
        BenchmarkRule(label=rule.label, phrase=rule.query.strip('"'), rule_group=rule.rule_group)
        for rule in load_query_rules()
        if rule.active and rule.language == "en"
    )
    timestamps = discover_batch_timestamps(
        now=scan_now,
        recent_hours=recent_hours,
        max_batches=max_batches,
        timeout_seconds=timeout_seconds,
    )
    measurements: list[BatchMeasurement] = []
    candidates_by_url: dict[str, Candidate] = {}
    skipped: list[datetime] = []
    for timestamp in timestamps:
        try:
            measurement, candidates = process_batch(
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
        for candidate in candidates:
            key = _canonical_url(candidate.url)
            if key not in candidates_by_url:
                candidates_by_url[key] = candidate
            else:
                existing = candidates_by_url[key]
                candidates_by_url[key] = Candidate(
                    timestamp=existing.timestamp,
                    language=existing.language,
                    title=existing.title,
                    url=existing.url,
                    rules=tuple(sorted(set(existing.rules) | set(candidate.rules))),
                )
    finished_at = datetime.now(UTC)
    return BenchmarkResult(
        started_at=started_at,
        finished_at=finished_at,
        recent_hours=recent_hours,
        measurements=tuple(measurements),
        candidates=tuple(candidates_by_url.values()),
        skipped_timestamps=tuple(skipped),
    )


def process_batch(
    timestamp: datetime,
    rules: tuple[BenchmarkRule, ...],
    *,
    timeout_seconds: float,
    output_directory: Path | None,
) -> tuple[BatchMeasurement, tuple[Candidate, ...]]:
    with temporary_batch_files(output_directory) as paths:
        ngram_bytes, ngram_download_seconds = download_file(
            _url_for(timestamp, "ngrams.txt.gz"), paths.ngram, timeout_seconds
        )
        scan_started = perf_counter()
        with gzip.open(paths.ngram, "rt", encoding="utf-8", errors="replace") as handle:
            matched_docids = scan_ngram(handle, rules)
        scan_seconds = perf_counter() - scan_started
        paths.ngram.unlink()

        toc_bytes, toc_download_seconds = download_file(
            _url_for(timestamp, "toc.json.gz"), paths.toc, timeout_seconds
        )
        toc_started = perf_counter()
        with gzip.open(paths.toc, "rt", encoding="utf-8", errors="replace") as handle:
            resolution = process_toc(handle, matched_docids, timestamp)
        toc_processing_seconds = perf_counter() - toc_started
        peak_temp_disk_bytes = max(ngram_bytes, toc_bytes)
        measurement = BatchMeasurement(
            timestamp=timestamp,
            ngram_compressed_bytes=ngram_bytes,
            toc_compressed_bytes=toc_bytes,
            ngram_download_seconds=ngram_download_seconds,
            toc_download_seconds=toc_download_seconds,
            scan_seconds=scan_seconds,
            toc_processing_seconds=toc_processing_seconds,
            documents_represented=resolution.documents_represented,
            matched_docids=len(matched_docids),
            unique_candidate_urls=len(resolution.candidates),
            peak_rss_bytes=peak_rss_bytes(),
            peak_temp_disk_bytes=peak_temp_disk_bytes,
        )
        return measurement, resolution.candidates


def aggregate_metrics(
    measurements: Iterable[BatchMeasurement],
    *,
    recent_hours: float,
    elapsed_seconds: float | None = None,
    unique_candidate_urls: int | None = None,
) -> AggregateMetrics:
    rows = tuple(measurements)
    total_download_bytes = sum(row.total_download_bytes for row in rows)
    download_seconds = sum(row.ngram_download_seconds + row.toc_download_seconds for row in rows)
    scan_seconds = sum(row.scan_seconds for row in rows)
    toc_processing_seconds = sum(row.toc_processing_seconds for row in rows)
    mb_per_hour = total_download_bytes / 1_000_000 / recent_hours if recent_hours else 0.0
    gb_per_day = mb_per_hour * 24 / 1_000
    gb_per_month = gb_per_day * 30
    rss_values = [row.peak_rss_bytes for row in rows if row.peak_rss_bytes is not None]
    return AggregateMetrics(
        batches_processed=len(rows),
        total_download_bytes=total_download_bytes,
        candidate_urls=sum(row.unique_candidate_urls for row in rows),
        unique_candidate_urls=(
            unique_candidate_urls
            if unique_candidate_urls is not None
            else sum(row.unique_candidate_urls for row in rows)
        ),
        documents_represented=sum(row.documents_represented for row in rows),
        matched_docids=sum(row.matched_docids for row in rows),
        elapsed_seconds=elapsed_seconds or 0.0,
        download_seconds=download_seconds,
        scan_seconds=scan_seconds,
        toc_processing_seconds=toc_processing_seconds,
        peak_rss_bytes=max(rss_values) if rss_values else None,
        peak_temp_disk_bytes=max((row.peak_temp_disk_bytes for row in rows), default=0),
        estimated_mb_per_hour=mb_per_hour,
        estimated_gb_per_day=gb_per_day,
        estimated_gb_per_month=gb_per_month,
        projected_vps_total_gb_month=VPS_BASELINE_GB_PER_MONTH + gb_per_month,
    )


def _mb(value: int) -> float:
    return value / 1_000_000


def _seconds(value: float) -> str:
    return f"{value:.2f}s"


def _top_lines(counter: Counter[str], limit: int = 10) -> str:
    return "\n".join(f"  {name}: {count}" for name, count in counter.most_common(limit)) or "  none"


def format_report(result: BenchmarkResult, *, example_limit: int = 30) -> str:
    totals = result.totals
    rule_counts: Counter[str] = Counter()
    language_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    for candidate in result.candidates:
        rule_counts.update(candidate.rules)
        language_counts.update([candidate.language])
        domain_counts.update([candidate.domain])
    lines = [
        "GDELT Web Legacy NGram benchmark (non-production)",
        f"Time window scanned: last {result.recent_hours:g} hours UTC; "
        f"safe lag {SAFE_LAG_MINUTES} minutes",
        f"Batches discovered: {len(result.measurements) + len(result.skipped_timestamps)}",
        f"Batches processed: {totals.batches_processed}",
        f"Batches skipped after discovery: {len(result.skipped_timestamps)}",
        "",
        "Per-batch measurements:",
    ]
    if not result.measurements:
        lines.append("  none")
    for row in result.measurements:
        lines.extend(
            [
                f"  {row.timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')}",
                f"    ngram compressed: {_mb(row.ngram_compressed_bytes):.3f} MB",
                f"    toc compressed: {_mb(row.toc_compressed_bytes):.3f} MB",
                f"    total downloaded: {_mb(row.total_download_bytes):.3f} MB",
                f"    download: {_seconds(row.ngram_download_seconds + row.toc_download_seconds)} "
                f"(ngram {_seconds(row.ngram_download_seconds)}, "
                f"toc {_seconds(row.toc_download_seconds)})",
                f"    scan: {_seconds(row.scan_seconds)}; "
                f"TOC processing: {_seconds(row.toc_processing_seconds)}",
                f"    documents represented: {row.documents_represented}; "
                f"matched DOCIDs: {row.matched_docids}; "
                f"unique candidate URLs: {row.unique_candidate_urls}",
                f"    peak RSS: {_mb(row.peak_rss_bytes):.1f} MB"
                if row.peak_rss_bytes
                else "    peak RSS: unavailable",
                f"    peak temp disk: {_mb(row.peak_temp_disk_bytes):.3f} MB",
            ]
        )
    lines.extend(
        [
            "",
            "Totals:",
            f"  elapsed benchmark duration: {_seconds(totals.elapsed_seconds)}",
            f"  total download: {_mb(totals.total_download_bytes):.3f} MB",
            f"  average MB/batch: {_mb(totals.total_download_bytes) / totals.batches_processed:.3f}"
            if totals.batches_processed
            else "  average MB/batch: 0.000",
            f"  candidate URLs: {totals.candidate_urls}",
            f"  unique candidate URLs: {totals.unique_candidate_urls}",
            f"  MB per unique candidate: "
            f"{_mb(totals.total_download_bytes) / totals.unique_candidate_urls:.3f}"
            if totals.unique_candidate_urls
            else "  MB per unique candidate: n/a",
            f"  download seconds: {_seconds(totals.download_seconds)}",
            f"  scan seconds: {_seconds(totals.scan_seconds)}",
            f"  TOC processing seconds: {_seconds(totals.toc_processing_seconds)}",
            f"  peak RAM: {_mb(totals.peak_rss_bytes):.1f} MB"
            if totals.peak_rss_bytes
            else "  peak RAM: unavailable",
            f"  peak temp disk: {_mb(totals.peak_temp_disk_bytes):.3f} MB",
            "",
            "Extrapolation from observed batch density in scanned window:",
            f"  estimated MB/hour: {totals.estimated_mb_per_hour:.3f}",
            f"  estimated GB/day: {totals.estimated_gb_per_day:.3f}",
            f"  estimated GB/30-day month: {totals.estimated_gb_per_month:.3f}",
            f"  current VPS baseline: {VPS_BASELINE_GB_PER_DAY:.2f} GB/day; "
            f"{VPS_BASELINE_GB_PER_MONTH:.0f} GB/month",
            f"  projected baseline + NGram traffic: "
            f"{totals.projected_vps_total_gb_month:.3f} GB/month",
            "  baseline is approximate whole-VPS interface traffic, not "
            "EpiSignal-only billing data",
            "",
            "Top matching rules:",
            _top_lines(rule_counts),
            "Top languages:",
            _top_lines(language_counts),
            "Top domains:",
            _top_lines(domain_counts),
            "",
            f"Example candidates (up to {example_limit}):",
        ]
    )
    if result.candidates:
        for candidate in result.candidates[:example_limit]:
            lines.append(
                f"  {candidate.timestamp} | {candidate.language} | {', '.join(candidate.rules)} | "
                f"{candidate.title} | {candidate.domain} | {candidate.url}"
            )
    else:
        lines.append("  none")
    return "\n".join(lines) + "\n"


def _bounded_float(value: str) -> float:
    parsed = float(value)
    if not 0 < parsed <= MAX_RECENT_HOURS:
        raise argparse.ArgumentTypeError(f"must be between 0 and {MAX_RECENT_HOURS:g}")
    return parsed


def _bounded_batches(value: str) -> int:
    parsed = int(value)
    if not 0 < parsed <= MAX_BATCHES:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_BATCHES}")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recent-hours", type=_bounded_float, default=6.0)
    parser.add_argument("--max-batches", type=_bounded_batches, default=MAX_BATCHES)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path, help="Also write the safe text report to this path")
    arguments = parser.parse_args(argv)
    try:
        result = run_benchmark(
            recent_hours=arguments.recent_hours,
            max_batches=arguments.max_batches,
            timeout_seconds=arguments.timeout_seconds,
        )
    except ValueError as exc:
        parser.error(str(exc))
    report = format_report(result)
    print(report, end="")
    if arguments.output:
        arguments.output.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
