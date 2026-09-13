import httpx
from episignal_backend.ai.routing import NoProviderKey
from episignal_backend.diagnostics import (
    FailureCategory,
    classify_ai_failure,
    classify_exception,
    classify_retrieval_failure,
)


def test_ai_failures_are_classified_without_preserving_provider_payloads() -> None:
    assert classify_ai_failure("ConnectTimeout") == FailureCategory.CONNECT_TIMEOUT
    assert classify_ai_failure("ReadTimeout") == FailureCategory.READ_TIMEOUT
    assert classify_ai_failure("429") == FailureCategory.HTTP_429
    assert classify_ai_failure("503") == FailureCategory.HTTP_5XX
    assert classify_ai_failure("no choices in the response") == FailureCategory.MALFORMED_RESPONSE
    assert classify_ai_failure("no adapter for model") == FailureCategory.PROVIDER_UNAVAILABLE
    assert classify_ai_failure("shape", rejected=True) == FailureCategory.SCHEMA_PARSE_ERROR
    assert classify_ai_failure("not_json", rejected=True) == FailureCategory.SCHEMA_PARSE_ERROR


def test_provider_http_exception_status_is_classified() -> None:
    response = httpx.Response(403, request=httpx.Request("POST", "https://example.test"))
    error = httpx.HTTPStatusError("forbidden", request=response.request, response=response)

    assert classify_exception(error) == FailureCategory.HTTP_403


def test_wrapped_missing_provider_is_classified_from_exception_type() -> None:
    error = RuntimeError("safe wrapper")
    error.__cause__ = NoProviderKey("configuration unavailable")

    assert classify_exception(error) == FailureCategory.PROVIDER_UNAVAILABLE


def test_retrieval_categories_include_transport_content_and_robots_failures() -> None:
    assert classify_retrieval_failure("", category="connect_timeout") == (
        FailureCategory.CONNECT_TIMEOUT
    )
    assert classify_retrieval_failure("example.test returned 429") == FailureCategory.HTTP_429
    assert classify_retrieval_failure("example.test returned no article body") == (
        FailureCategory.INVALID_CONTENT
    )
    assert classify_retrieval_failure("robots disallowed") == FailureCategory.BLOCKED_ROBOTS
