"""GDELT DOC 2.0 client.

Verified against the live API on 2026-08-27: an `ArtList` response is a JSON
object with one `articles` key, and each entry carries `url`, `url_mobile`,
`title`, `seendate`, `socialimage`, `domain`, `language`, and `sourcecountry`.
There is no publication date and no body text, which is why `article.py` exists.

`seendate` is quantized to fifteen minutes and records when the GDELT crawler
saw the article. It is stored as `gdelt_seen_at` and never as `published_at`.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from time import sleep as default_sleep
from typing import Any

import httpx

from episignal_backend.ingestion.documents import DiscoveredArticle, QueryRule, TimeWindow
from episignal_backend.ingestion.gdelt.locale import country_code, language_code
from episignal_backend.ingestion.urls import canonicalize_url

logger = logging.getLogger("episignal_backend.ingestion.gdelt.api")

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
HTTP_FALLBACK_URL = "http://api.gdeltproject.org/api/v2/doc/doc"
MAX_RECORDS = 250
TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 3
CIRCUIT_FAILURE_THRESHOLD = 8
CIRCUIT_FAILURE_ELAPSED_BUDGET_SEC = 180.0
SEEN_FORMAT = "%Y%m%dT%H%M%SZ"
WINDOW_FORMAT = "%Y%m%d%H%M%S"
# The `sourcelang:` operator wants GDELT's three-letter codes, while query
# rules carry the two-letter codes the rest of the pipeline stores. A rule
# language without an entry here still gets the result-side guard below; it
# just does not also narrow the search at the API.
LANGUAGE_OPERATOR_CODES: dict[str, str] = {
    "en": "eng",
}


class GdeltUnavailable(Exception):
    """GDELT could not be reached or kept refusing.

    Expected rather than exceptional: the API rate-limits aggressively, and one
    unreachable rule must not fail a run covering fifty others.
    """

    def __init__(
        self, message: str = "GDELT search failed", *, failure: "GdeltFailure | None" = None
    ) -> None:
        super().__init__(message)
        self.failure = failure


@dataclass(frozen=True)
class GdeltFailure:
    category: str
    transport: str
    status_code: int | None
    elapsed_ms: float
    detail: str


@dataclass(frozen=True)
class GdeltRunSummary:
    rules_total: int
    rules_attempted: int
    rules_succeeded: int
    rules_failed: int
    rules_skipped_circuit: int
    https_attempts: int
    http_attempts: int
    failure_counts: dict[str, int]
    circuit_open: bool
    circuit_open_reason: str | None
    failure_streak_elapsed_sec: float


class GdeltCircuitBreaker:
    def __init__(
        self,
        threshold: int = CIRCUIT_FAILURE_THRESHOLD,
        elapsed_budget_sec: float = CIRCUIT_FAILURE_ELAPSED_BUDGET_SEC,
    ) -> None:
        self.threshold = threshold
        self.elapsed_budget_sec = elapsed_budget_sec
        self.failure_streak = 0
        self.failure_streak_elapsed_sec = 0.0
        self.open = False
        self.open_reason: str | None = None
        self.skipped = 0

    def record_success(self) -> None:
        self.failure_streak = 0
        self.failure_streak_elapsed_sec = 0.0

    def record_failure(self, elapsed_sec: float) -> None:
        self.failure_streak += 1
        self.failure_streak_elapsed_sec += elapsed_sec
        if self.failure_streak >= self.threshold and self.open_reason is None:
            self.open = True
            self.open_reason = "consecutive_failures"
        elif (
            self.failure_streak_elapsed_sec >= self.elapsed_budget_sec and self.open_reason is None
        ):
            self.open = True
            self.open_reason = "failure_time_budget"


class _PayloadFailure(Exception):
    def __init__(self, category: str, status_code: int | None, detail: str) -> None:
        super().__init__(detail)
        self.category = category
        self.status_code = status_code
        self.detail = detail


def parse_seen_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), SEEN_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


class GdeltDocClient:
    discovery_name = "GDELT"

    def __init__(
        self,
        client: httpx.Client | None = None,
        fallback_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = default_sleep,
        monotonic: Callable[[], float] = perf_counter,
    ) -> None:
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._fallback_client = fallback_client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._sleep = sleep
        self._monotonic = monotonic
        self._https_unavailable = False
        self._circuit = GdeltCircuitBreaker()
        self._reset_run_metrics()

    @property
    def circuit_open(self) -> bool:
        return self._circuit.open

    def begin_run(self) -> None:
        """Reset all circuit and request state for one discovery run."""
        self._https_unavailable = False
        self._circuit = GdeltCircuitBreaker()
        self._reset_run_metrics()

    def _reset_run_metrics(self) -> None:
        self._rules_attempted = 0
        self._rules_succeeded = 0
        self._rules_failed = 0
        self._https_attempts = 0
        self._http_attempts = 0
        self._failure_counts = {
            category: 0
            for category in (
                "connect_timeout",
                "read_timeout",
                "tls_error",
                "http_429",
                "http_5xx",
                "invalid_response",
                "parse_error",
                "other",
            )
        }

    def finish_run(self, rules_total: int) -> GdeltRunSummary:
        if self._circuit.open:
            logger.warning(
                "gdelt_circuit_open reason=%s consecutive_failures=%d "
                "failure_elapsed_sec=%.1f remaining_rules=%d",
                self._circuit.open_reason,
                self._circuit.failure_streak,
                self._circuit.failure_streak_elapsed_sec,
                max(0, rules_total - self._rules_attempted),
            )
        summary = GdeltRunSummary(
            rules_total=rules_total,
            rules_attempted=self._rules_attempted,
            rules_succeeded=self._rules_succeeded,
            rules_failed=self._rules_failed,
            rules_skipped_circuit=self._circuit.skipped,
            https_attempts=self._https_attempts,
            http_attempts=self._http_attempts,
            failure_counts=dict(self._failure_counts),
            circuit_open=self._circuit.open,
            circuit_open_reason=self._circuit.open_reason,
            failure_streak_elapsed_sec=self._circuit.failure_streak_elapsed_sec,
        )
        logger.info(
            "gdelt_run_summary rules_total=%d rules_attempted=%d rules_succeeded=%d "
            "rules_failed=%d rules_skipped_circuit=%d https_attempts=%d http_attempts=%d "
            "failure_connect_timeout=%d failure_read_timeout=%d failure_tls_error=%d "
            "failure_http_429=%d failure_http_5xx=%d failure_invalid_response=%d "
            "failure_parse_error=%d failure_other=%d circuit_open=%s "
            "circuit_open_reason=%s failure_streak_elapsed_sec=%.1f",
            summary.rules_total,
            summary.rules_attempted,
            summary.rules_succeeded,
            summary.rules_failed,
            summary.rules_skipped_circuit,
            summary.https_attempts,
            summary.http_attempts,
            summary.failure_counts["connect_timeout"],
            summary.failure_counts["read_timeout"],
            summary.failure_counts["tls_error"],
            summary.failure_counts["http_429"],
            summary.failure_counts["http_5xx"],
            summary.failure_counts["invalid_response"],
            summary.failure_counts["parse_error"],
            summary.failure_counts["other"],
            str(summary.circuit_open).lower(),
            summary.circuit_open_reason or "null",
            summary.failure_streak_elapsed_sec,
        )
        return summary

    def search(self, rule: QueryRule, window: TimeWindow) -> tuple[DiscoveredArticle, ...]:
        if self._circuit.open:
            self._circuit.skipped += 1
            return ()

        self._rules_attempted += 1
        query = rule.query
        operator = LANGUAGE_OPERATOR_CODES.get(rule.language)
        if operator is not None:
            query = f"{query} sourcelang:{operator}"
        parameters = {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": str(MAX_RECORDS),
            "sort": "datedesc",
            "startdatetime": window.start.astimezone(UTC).strftime(WINDOW_FORMAT),
            "enddatetime": window.end.astimezone(UTC).strftime(WINDOW_FORMAT),
        }
        rule_started = self._monotonic()
        try:
            payload = self._request(parameters)
        except GdeltUnavailable as error:
            self._rules_failed += 1
            failure = error.failure or GdeltFailure("other", "https", None, 0.0, str(error))
            self._failure_counts[failure.category] += 1
            self._circuit.record_failure(self._monotonic() - rule_started)
            logger.warning(
                "gdelt_rule_failed rule=%s rule_id=%s transport=%s error=%s "
                "status_code=%s elapsed_ms=%.1f detail=%s",
                rule.label,
                rule.id,
                failure.transport,
                failure.category,
                failure.status_code,
                failure.elapsed_ms,
                failure.detail,
            )
            raise

        self._rules_succeeded += 1
        self._circuit.record_success()
        entries = payload.get("articles")
        if not isinstance(entries, list):
            return ()

        articles: list[DiscoveredArticle] = []
        dropped_by_language = 0
        for entry in entries:
            article = self._article(entry, rule)
            if article is None:
                continue
            # The second half of language enforcement: the operator narrows the
            # search, this guard keeps a misreporting entry out regardless. An
            # unmapped name cannot be confirmed as the rule's language, so a
            # rule that pins one drops it rather than trusting it.
            if rule.language != "any" and article.language != rule.language:
                dropped_by_language += 1
                continue
            articles.append(article)
        if dropped_by_language:
            logger.debug("Dropped %d entries not reporting the rule language", dropped_by_language)
        return tuple(articles)

    def _article(self, entry: object, rule: QueryRule) -> DiscoveredArticle | None:
        if not isinstance(entry, dict):
            return None
        url = str(entry.get("url") or "").strip()
        title = str(entry.get("title") or "").strip()
        domain = str(entry.get("domain") or "").strip()
        seen = parse_seen_date(str(entry.get("seendate") or ""))
        if not url or not title or not domain or seen is None:
            # A partial entry names no document we could ever fetch, so there is
            # nothing to keep and nothing to review.
            return None
        return DiscoveredArticle(
            url=url,
            canonical_url=canonicalize_url(url),
            title=title,
            domain=domain,
            gdelt_seen_at=seen,
            language=language_code(str(entry.get("language") or "")),
            country_code=country_code(str(entry.get("sourcecountry") or "")),
            query_rule_id=rule.id,
        )

    def _request(self, parameters: dict[str, str]) -> dict[str, Any]:
        last_failure: GdeltFailure | None = None

        for attempt in range(MAX_ATTEMPTS):
            transport = "http" if self._https_unavailable else "https"
            client = self._fallback_client if transport == "http" else self._client
            payload, failure = self._attempt(client, transport, parameters)
            if payload is not None:
                return payload
            assert failure is not None
            last_failure = failure

            if transport == "https" and failure.category in {
                "connect_timeout",
                "read_timeout",
                "tls_error",
            }:
                self._https_unavailable = True
                payload, fallback_failure = self._attempt(self._fallback_client, "http", parameters)
                if payload is not None:
                    return payload
                assert fallback_failure is not None
                last_failure = fallback_failure

            if attempt < MAX_ATTEMPTS - 1:
                self._sleep(2.0**attempt)

        raise GdeltUnavailable("GDELT search failed", failure=last_failure)

    def _attempt(
        self,
        client: httpx.Client,
        transport: str,
        parameters: dict[str, str],
    ) -> tuple[dict[str, Any] | None, GdeltFailure | None]:
        if transport == "https":
            self._https_attempts += 1
        else:
            self._http_attempts += 1
        started = perf_counter()
        try:
            response = client.get(
                API_URL if transport == "https" else HTTP_FALLBACK_URL,
                params=parameters,
                timeout=TIMEOUT_SECONDS,
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            return None, GdeltFailure(
                category=self._transport_category(error),
                transport=transport,
                status_code=None,
                elapsed_ms=(perf_counter() - started) * 1000,
                detail=str(error) or type(error).__name__,
            )

        try:
            payload = self._response_payload(response)
        except _PayloadFailure as error:
            return None, GdeltFailure(
                category=error.category,
                transport=transport,
                status_code=error.status_code,
                elapsed_ms=(perf_counter() - started) * 1000,
                detail=error.detail,
            )
        return payload, None

    @staticmethod
    def _transport_category(error: Exception) -> str:
        if isinstance(error, httpx.ConnectTimeout):
            return "connect_timeout"
        if isinstance(error, httpx.ReadTimeout):
            return "read_timeout"
        if isinstance(error, httpx.TimeoutException):
            return "read_timeout"
        detail = f"{error} {error.__cause__ or ''}".lower()
        if isinstance(error, httpx.ConnectError) and any(
            marker in detail for marker in ("tls", "ssl", "certificate", "handshake")
        ):
            return "tls_error"
        return "other"

    @staticmethod
    def _response_payload(response: httpx.Response) -> dict[str, Any] | None:
        if response.status_code == 429:
            raise _PayloadFailure("http_429", response.status_code, "GDELT returned HTTP 429")
        if 500 <= response.status_code <= 599:
            raise _PayloadFailure(
                "http_5xx", response.status_code, f"GDELT returned HTTP {response.status_code}"
            )
        if not 200 <= response.status_code < 300:
            raise _PayloadFailure(
                "invalid_response",
                response.status_code,
                f"GDELT returned HTTP {response.status_code}",
            )
        try:
            payload = response.json()
        except ValueError as error:
            # GDELT answers an unmatched query with a bare sentence rather
            # than JSON, which means no results, not a fault.
            if response.text.strip().lower().startswith("no results"):
                return {}
            raise _PayloadFailure(
                "parse_error", response.status_code, "GDELT returned non-JSON"
            ) from error
        if not isinstance(payload, dict) or not isinstance(payload.get("articles"), list):
            raise _PayloadFailure("invalid_response", response.status_code, "GDELT response schema")
        return payload
