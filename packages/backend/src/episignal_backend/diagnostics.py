"""Safe, low-cardinality failure categories for operational diagnostics.

These helpers deliberately inspect exception types, HTTP status codes, and
already-safe reason labels only. They never persist exception messages or
provider/page payloads.
"""

import re
from enum import StrEnum
from typing import Any


class FailureCategory(StrEnum):
    CONNECT_TIMEOUT = "connect_timeout"
    READ_TIMEOUT = "read_timeout"
    TIMEOUT = "timeout"
    DNS_CONNECT_ERROR = "dns_connect_error"
    HTTP_403 = "http_403"
    HTTP_429 = "http_429"
    HTTP_5XX = "http_5xx"
    HTTP_OTHER = "http_other"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MALFORMED_RESPONSE = "malformed_response"
    SCHEMA_PARSE_ERROR = "schema_parse_error"
    BLOCKED_ROBOTS = "blocked_robots"
    INVALID_CONTENT = "invalid_content"
    PARSER_FAILURE = "parser_failure"
    STORAGE_FAILURE = "storage_failure"
    OTHER = "other"


_STATUS_PATTERN = re.compile(r"\b([1-5][0-9]{2})\b")


def _status_category(status: Any) -> FailureCategory | None:
    if not isinstance(status, int) or isinstance(status, bool):
        return None
    if status == 403:
        return FailureCategory.HTTP_403
    if status == 429:
        return FailureCategory.HTTP_429
    if 500 <= status <= 599:
        return FailureCategory.HTTP_5XX
    if 400 <= status <= 499:
        return FailureCategory.HTTP_OTHER
    return None


def classify_ai_failure(
    reason: str | None,
    *,
    http_status: int | None = None,
    rejected: bool = False,
) -> FailureCategory:
    """Classify one provider or answer failure from safe request telemetry."""
    status_category = _status_category(http_status)
    if status_category is not None:
        return status_category

    normalized = (reason or "").strip().lower()
    if rejected:
        if normalized.startswith(("not_json", "shape")):
            return FailureCategory.SCHEMA_PARSE_ERROR
        return FailureCategory.MALFORMED_RESPONSE
    if normalized in {"connecttimeout", "connect_timeout"}:
        return FailureCategory.CONNECT_TIMEOUT
    if normalized in {"readtimeout", "read_timeout"}:
        return FailureCategory.READ_TIMEOUT
    if normalized in {"timeoutexception", "timeout"}:
        return FailureCategory.TIMEOUT
    status_match = _STATUS_PATTERN.search(normalized)
    if status_match:
        status_category = _status_category(int(status_match.group(1)))
        if status_category is not None:
            return status_category
    if "no choices" in normalized or "no message content" in normalized:
        return FailureCategory.MALFORMED_RESPONSE
    if "no adapter" in normalized or "no provider" in normalized:
        return FailureCategory.PROVIDER_UNAVAILABLE
    if "dns" in normalized or "connecterror" in normalized:
        return FailureCategory.DNS_CONNECT_ERROR
    if "provider" in normalized or "unavailable" in normalized:
        return FailureCategory.PROVIDER_UNAVAILABLE
    return FailureCategory.OTHER


def classify_retrieval_failure(
    reason: str | None,
    *,
    category: str | None = None,
) -> FailureCategory:
    """Classify a retrieval failure without changing whether it is retried."""
    if category:
        try:
            return FailureCategory(category)
        except ValueError:
            pass

    normalized = (reason or "").strip().lower()
    if "robots" in normalized or "disallow" in normalized:
        return FailureCategory.BLOCKED_ROBOTS
    if "connecttimeout" in normalized:
        return FailureCategory.CONNECT_TIMEOUT
    if "readtimeout" in normalized:
        return FailureCategory.READ_TIMEOUT
    if "timeout" in normalized:
        return FailureCategory.TIMEOUT
    status_match = _STATUS_PATTERN.search(normalized)
    if status_match:
        status_category = _status_category(int(status_match.group(1)))
        if status_category is not None:
            return status_category
    if "no article body" in normalized or "content-type" in normalized or "oversized" in normalized:
        return FailureCategory.INVALID_CONTENT
    if "parser" in normalized or "parse" in normalized:
        return FailureCategory.PARSER_FAILURE
    if "dns" in normalized or "connect" in normalized:
        return FailureCategory.DNS_CONNECT_ERROR
    return FailureCategory.OTHER


def classify_exception(error: BaseException) -> FailureCategory:
    """Classify a stage-level exception using type and safe status metadata."""
    name = type(error).__name__
    cause = error.__cause__
    if cause is not None and type(cause).__name__ in {"NoProviderKey", "NoModelsConfigured"}:
        return FailureCategory.PROVIDER_UNAVAILABLE
    if name == "ConnectTimeout":
        return FailureCategory.CONNECT_TIMEOUT
    if name == "ReadTimeout":
        return FailureCategory.READ_TIMEOUT
    if name == "TimeoutException":
        return FailureCategory.TIMEOUT

    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    status_category = _status_category(status)
    if status_category is not None:
        return status_category
    explicit_status = getattr(error, "status_code", None)
    status_category = _status_category(explicit_status)
    if status_category is not None:
        return status_category

    explicit_category = getattr(error, "category", None)
    if isinstance(explicit_category, str):
        try:
            return FailureCategory(explicit_category)
        except ValueError:
            pass
    if name in {"NoProviderKey", "NoModelsConfigured"}:
        return FailureCategory.PROVIDER_UNAVAILABLE
    if name in {"ModelUnavailable", "CredentialRejected"}:
        return classify_ai_failure(str(error))
    if name in {"Disallowed"}:
        return FailureCategory.BLOCKED_ROBOTS
    if name in {"Unfetchable", "RetrievalFailed"}:
        return classify_retrieval_failure(str(error))
    if name in {"JSONDecodeError", "JSONDecodeException"}:
        return FailureCategory.MALFORMED_RESPONSE
    if name in {"Rejected", "ValidationError"}:
        return FailureCategory.SCHEMA_PARSE_ERROR
    if name == "RuntimeError" and "provider key" in str(error).lower():
        return FailureCategory.PROVIDER_UNAVAILABLE
    if "dns" in name.lower() or "connect" in name.lower():
        return FailureCategory.DNS_CONNECT_ERROR
    return FailureCategory.OTHER
