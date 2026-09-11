"""Production GDELT Web Legacy NGram discovery.

NGram batches are source files, not an API query. This module keeps the batch
boundary explicit: inventory only complete NGram/TOC pairs, process one pair at
a time, and expose the cursor only after the caller has stored its candidates.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import tempfile
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from episignal_backend.ingestion.documents import DiscoveredArticle, QueryRule, TimeWindow
from episignal_backend.ingestion.gdelt.locale import country_code, language_code
from episignal_backend.ingestion.urls import canonicalize_url

logger = logging.getLogger("episignal_backend.ingestion.gdelt.ngram")

BASE_URL = "https://data.gdeltproject.org/gdeltv5/weblegacy/ngrams"
SAFE_LAG_MINUTES = 5
DEFAULT_MAX_CATCHUP_MINUTES = 6 * 60
DEFAULT_MAX_BATCHES = 64
DEFAULT_MAX_DOWNLOAD_BYTES = 1_500_000_000
DEFAULT_TIMEOUT_SECONDS = 30.0
TOKEN_RE = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)


class NgramProviderStatus(StrEnum):
    HEALTHY = "healthy"
    PARTIAL = "partial_degradation"
    UNAVAILABLE = "unavailable"


class NgramCursorStore(Protocol):
    def get_cursor(self) -> datetime | None: ...

    def set_cursor(self, value: datetime) -> None: ...


@dataclass(frozen=True)
class NgramBatch:
    timestamp: datetime
    ngram_url: str
    toc_url: str


@dataclass(frozen=True)
class NgramInventory:
    batches: tuple[NgramBatch, ...]
    minutes_checked: int
    ngram_files_seen: int
    toc_files_seen: int
    transport_failures: int


@dataclass(frozen=True)
class TemporaryBatchFiles:
    directory: Path
    ngram: Path
    toc: Path


@dataclass(frozen=True)
class NgramTocResult:
    documents_scanned: int
    language_filtered_candidates: int
    articles: tuple[DiscoveredArticle, ...]


@dataclass
class NgramRunMetrics:
    minutes_checked: int = 0
    ngram_files_seen: int = 0
    toc_files_seen: int = 0
    complete_pairs: int = 0
    batches_attempted: int = 0
    batches_succeeded: int = 0
    batches_failed: int = 0
    bytes_downloaded: int = 0
    documents_scanned: int = 0
    raw_matched_docids: int = 0
    language_filtered_candidates: int = 0
    unique_candidates: int = 0
    catchup_minutes: int = 0
    cursor_before: datetime | None = None
    cursor_after: datetime | None = None

    def as_dict(self) -> dict[str, int | str | None]:
        result: dict[str, int | str | None] = {key: value for key, value in self.__dict__.items()}
        for key in ("cursor_before", "cursor_after"):
            value = result[key]
            result[key] = value.isoformat() if isinstance(value, datetime) else None
        return result


@dataclass(frozen=True)
class NgramDiscoveryResult:
    candidates: tuple[DiscoveredArticle, ...]
    status: NgramProviderStatus
    metrics: NgramRunMetrics
    cursor_after: datetime | None


@dataclass(frozen=True)
class _NgramRule:
    rule: QueryRule
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class _RuleIndex:
    by_first_token: dict[str, tuple[_NgramRule, ...]]


def tokenize(value: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold() for match in TOKEN_RE.finditer(value))


def build_rule_index(rules: Iterable[QueryRule]) -> _RuleIndex:
    by_first_token: dict[str, list[_NgramRule]] = {}
    for rule in rules:
        tokens = tokenize(rule.query.strip('"'))
        if tokens:
            by_first_token.setdefault(tokens[0], []).append(_NgramRule(rule, tokens))
    return _RuleIndex({key: tuple(value) for key, value in by_first_token.items()})


def _match_rule_index(words: tuple[str, ...], index: _RuleIndex) -> tuple[str, ...]:
    matched: set[str] = set()
    for position, word in enumerate(words):
        for item in index.by_first_token.get(word, ()):
            if words[position : position + len(item.tokens)] == item.tokens:
                matched.add(item.rule.label)
    return tuple(sorted(matched))


def match_rules(quadgram: str, rules: Iterable[QueryRule]) -> tuple[str, ...]:
    return _match_rule_index(tokenize(quadgram), build_rule_index(rules))


def parse_ngram_rows(handle: TextIO) -> Iterator[tuple[int, str, int]]:
    for line_number, raw_line in enumerate(handle, start=1):
        line = raw_line.rstrip("\r\n")
        if not line:
            continue
        columns = line.split("\t")
        if len(columns) != 3:
            raise ValueError(f"NGram line {line_number} has {len(columns)} columns")
        try:
            yield int(columns[0]), columns[1], int(columns[2])
        except ValueError as error:
            raise ValueError(f"NGram line {line_number} has invalid numeric field") from error


def scan_ngram(handle: TextIO, rules: Iterable[QueryRule]) -> dict[int, set[str]]:
    index = build_rule_index(rules)
    matched: dict[int, set[str]] = {}
    for docid, quadgram, _count in parse_ngram_rows(handle):
        labels = _match_rule_index(tokenize(quadgram), index)
        if labels:
            matched.setdefault(docid, set()).update(labels)
    return matched


def _toc_timestamp(value: object, fallback: datetime) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            pass
    return fallback


def _toc_language(value: object) -> str | None:
    raw = str(value or "").strip()
    if len(raw) == 2:
        return raw.casefold()
    return language_code(raw)


def process_toc(
    handle: TextIO,
    matched_docids: dict[int, set[str]],
    rules: Sequence[QueryRule],
    batch_timestamp: datetime,
) -> NgramTocResult:
    by_label: dict[str, tuple[QueryRule, ...]] = {}
    for rule in rules:
        by_label[rule.label] = (*by_label.get(rule.label, ()), rule)

    documents_scanned = 0
    language_filtered = 0
    by_url: dict[str, DiscoveredArticle] = {}
    for line_number, raw_line in enumerate(handle, start=1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise ValueError(f"TOC line {line_number} is not valid JSON") from error
        if not isinstance(record, dict) or "ID" not in record:
            raise ValueError(f"TOC line {line_number} lacks ID")
        try:
            docid = int(record["ID"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"TOC line {line_number} has invalid ID") from error
        documents_scanned += 1
        labels = matched_docids.get(docid)
        if not labels:
            continue

        language = _toc_language(record.get("lang"))
        matching_rules = tuple(
            rule
            for label in labels
            for rule in by_label.get(label, ())
            if rule.language == "any" or language == rule.language
        )
        if not matching_rules:
            language_filtered += 1
            continue

        url = str(record.get("url") or "").strip()
        parsed = urlsplit(url)
        domain = parsed.hostname
        if not url or not domain:
            continue
        title = str(record.get("title") or "(untitled)").strip() or "(untitled)"
        article = DiscoveredArticle(
            url=url,
            canonical_url=canonicalize_url(url),
            title=title,
            domain=domain,
            gdelt_seen_at=_toc_timestamp(record.get("date"), batch_timestamp),
            language=language,
            country_code=country_code(str(record.get("sourcecountry") or "")),
            query_rule_id=matching_rules[0].id,
        )
        existing = by_url.get(article.canonical_url)
        if existing is None:
            by_url[article.canonical_url] = article

    return NgramTocResult(
        documents_scanned=documents_scanned,
        language_filtered_candidates=language_filtered,
        articles=tuple(by_url.values()),
    )


@contextmanager
def temporary_batch_files(base_dir: Path | None = None) -> Iterator[TemporaryBatchFiles]:
    with tempfile.TemporaryDirectory(dir=base_dir, prefix="episignal-gdelt-") as raw_dir:
        directory = Path(raw_dir)
        yield TemporaryBatchFiles(
            directory=directory,
            ngram=directory / "batch.ngrams.txt.gz",
            toc=directory / "batch.toc.json.gz",
        )


def _url_for(timestamp: datetime, suffix: str) -> str:
    stamp = timestamp.astimezone(UTC).strftime("%Y%m%d%H%M00")
    return f"{BASE_URL}/{stamp}.{suffix}"


class GdeltNgramClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
        opener: Callable[..., Any] = urlopen,
        user_agent: str = "EpiSignal-NGram/1.0",
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_download_bytes = max_download_bytes
        self._opener = opener
        self._user_agent = user_agent

    def _request(self, url: str, method: str = "GET") -> Any:
        return self._opener(
            Request(url, method=method, headers={"User-Agent": self._user_agent}),
            timeout=self.timeout_seconds,
        )

    def _available(self, url: str) -> tuple[bool, bool]:
        try:
            with self._request(url, method="HEAD") as response:
                return 200 <= int(getattr(response, "status", 200)) < 400, False
        except HTTPError as error:
            return False, error.code not in {404, 410}
        except (URLError, TimeoutError, OSError):
            return False, True

    def inventory(self, start: datetime, end: datetime, *, max_batches: int) -> NgramInventory:
        cursor = end.astimezone(UTC).replace(second=0, microsecond=0)
        lower = start.astimezone(UTC).replace(second=0, microsecond=0)
        found: list[NgramBatch] = []
        minutes_checked = 0
        ngram_files_seen = 0
        toc_files_seen = 0
        transport_failures = 0
        while cursor >= lower and len(found) < max_batches:
            minutes_checked += 1
            ngram_url = _url_for(cursor, "ngrams.txt.gz")
            toc_url = _url_for(cursor, "toc.json.gz")
            ngram_exists, ngram_failed = self._available(ngram_url)
            toc_exists, toc_failed = self._available(toc_url)
            ngram_files_seen += int(ngram_exists)
            toc_files_seen += int(toc_exists)
            transport_failures += int(ngram_failed) + int(toc_failed)
            if ngram_exists and toc_exists:
                found.append(NgramBatch(cursor, ngram_url, toc_url))
            cursor -= timedelta(minutes=1)
        return NgramInventory(
            batches=tuple(reversed(found)),
            minutes_checked=minutes_checked,
            ngram_files_seen=ngram_files_seen,
            toc_files_seen=toc_files_seen,
            transport_failures=transport_failures,
        )

    def download(self, url: str, destination: Path, *, max_bytes: int | None = None) -> int:
        limit = (
            self.max_download_bytes
            if max_bytes is None
            else min(self.max_download_bytes, max_bytes)
        )
        written = 0
        with self._request(url) as response, destination.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise ValueError("GDELT NGram download exceeds configured limit")
                handle.write(chunk)
        return written


def _inventory_value(
    inventory: NgramInventory | tuple[NgramBatch, ...],
) -> NgramInventory:
    if isinstance(inventory, NgramInventory):
        return inventory
    return NgramInventory(
        batches=inventory,
        minutes_checked=0,
        ngram_files_seen=len(inventory),
        toc_files_seen=len(inventory),
        transport_failures=0,
    )


class GdeltNgramDiscovery:
    def __init__(
        self,
        client: GdeltNgramClient,
        *,
        cursor_store: NgramCursorStore,
        max_catchup_minutes: int = DEFAULT_MAX_CATCHUP_MINUTES,
        max_batches: int = DEFAULT_MAX_BATCHES,
        max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
        temp_directory: Path | None = None,
    ) -> None:
        self._client = client
        self._cursor_store = cursor_store
        self._max_catchup_minutes = max_catchup_minutes
        self._max_batches = max_batches
        self._max_download_bytes = max_download_bytes
        self._temp_directory = temp_directory

    def discover_rules(
        self, rules: Sequence[QueryRule], window: TimeWindow
    ) -> NgramDiscoveryResult:
        cursor_before = self._cursor_store.get_cursor()
        safe_end = window.end.astimezone(UTC) - timedelta(minutes=SAFE_LAG_MINUTES)
        safe_end = safe_end.replace(second=0, microsecond=0)
        lower_bound = max(
            window.start.astimezone(UTC).replace(second=0, microsecond=0),
            safe_end - timedelta(minutes=self._max_catchup_minutes),
        )
        if cursor_before is not None:
            lower_bound = max(lower_bound, cursor_before.astimezone(UTC))

        metrics = NgramRunMetrics(
            catchup_minutes=max(0, int((safe_end - lower_bound).total_seconds() // 60)),
            cursor_before=cursor_before,
        )
        inventory = _inventory_value(
            self._client.inventory(lower_bound, safe_end, max_batches=self._max_batches)
        )
        metrics.minutes_checked = inventory.minutes_checked
        metrics.ngram_files_seen = inventory.ngram_files_seen
        metrics.toc_files_seen = inventory.toc_files_seen
        metrics.complete_pairs = len(inventory.batches)

        by_url: dict[str, DiscoveredArticle] = {}
        last_success: datetime | None = None
        for batch in inventory.batches:
            if metrics.bytes_downloaded >= self._max_download_bytes:
                break
            if cursor_before is not None and batch.timestamp <= cursor_before:
                continue
            metrics.batches_attempted += 1
            try:
                result = self._process_batch(
                    batch,
                    rules,
                    max_download_bytes=self._max_download_bytes - metrics.bytes_downloaded,
                )
            except Exception as error:
                metrics.batches_failed += 1
                logger.warning("GDELT NGram batch failed (%s)", type(error).__name__)
                break
            metrics.batches_succeeded += 1
            metrics.bytes_downloaded += result[0]
            toc = result[1]
            metrics.documents_scanned += toc.documents_scanned
            metrics.raw_matched_docids += result[2]
            metrics.language_filtered_candidates += toc.language_filtered_candidates
            last_success = batch.timestamp
            for article in toc.articles:
                by_url.setdefault(article.canonical_url, article)

        metrics.unique_candidates = len(by_url)
        metrics.cursor_after = last_success
        if metrics.batches_failed and metrics.batches_succeeded:
            status = NgramProviderStatus.PARTIAL
        elif metrics.batches_failed or inventory.transport_failures and not inventory.batches:
            status = NgramProviderStatus.UNAVAILABLE
        else:
            status = NgramProviderStatus.HEALTHY
        return NgramDiscoveryResult(tuple(by_url.values()), status, metrics, last_success)

    def complete(self, cursor_after: datetime | None, *, success: bool) -> None:
        if success and cursor_after is not None:
            self._cursor_store.set_cursor(cursor_after)

    def _process_batch(
        self,
        batch: NgramBatch,
        rules: Sequence[QueryRule],
        *,
        max_download_bytes: int,
    ) -> tuple[int, NgramTocResult, int]:
        with temporary_batch_files(self._temp_directory) as paths:
            ngram_bytes = self._client.download(
                batch.ngram_url, paths.ngram, max_bytes=max_download_bytes
            )
            with gzip.open(paths.ngram, "rt", encoding="utf-8", errors="replace") as handle:
                matched_docids = scan_ngram(handle, rules)
            toc_bytes = self._client.download(
                batch.toc_url, paths.toc, max_bytes=max_download_bytes - ngram_bytes
            )
            with gzip.open(paths.toc, "rt", encoding="utf-8", errors="replace") as handle:
                toc = process_toc(handle, matched_docids, rules, batch.timestamp)
            return ngram_bytes + toc_bytes, toc, len(matched_docids)
