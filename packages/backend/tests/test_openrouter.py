import json

import httpx
import pytest
from episignal_backend.ai.documents import ChatRequest
from episignal_backend.ai.openrouter import OpenRouterChatModel
from episignal_backend.ai.protocol import ModelUnavailable

REQUEST = ChatRequest(model_id="vendor/model:free", system="rules", user="article")


def model(handler: object, sleeps: list[float] | None = None) -> OpenRouterChatModel:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return OpenRouterChatModel(
        api_key="test-key",
        client=client,
        sleep=sleeps.append if sleeps is not None else (lambda s: None),
    )


def body(content: str, prompt: int = 900, completion: int = 120) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


def test_a_successful_call_returns_the_content_and_the_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body('{"ok": true}'))

    response = model(handler).complete(REQUEST)

    assert response.content == '{"ok": true}'
    assert response.usage.prompt_tokens == 900
    assert response.http_status == 200
    assert response.latency_ms >= 0


def test_the_request_names_the_model_and_carries_both_messages() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=body("{}"))

    model(handler).complete(REQUEST)

    assert seen[0]["model"] == "vendor/model:free"
    assert [message["role"] for message in seen[0]["messages"]] == ["system", "user"]


def test_the_api_key_travels_in_the_authorization_header() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json=body("{}"))

    model(handler).complete(REQUEST)

    assert seen[0] == "Bearer test-key"


def test_a_rate_limit_is_retried_and_then_succeeds() -> None:
    statuses = [429, 200]

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses.pop(0)
        return httpx.Response(status, json=body("{}") if status == 200 else {})

    sleeps: list[float] = []
    response = model(handler, sleeps).complete(REQUEST)

    assert response.http_status == 200
    assert len(sleeps) == 1


def test_a_persistent_rate_limit_is_unavailable_not_a_bad_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={})

    with pytest.raises(ModelUnavailable):
        model(handler).complete(REQUEST)


def test_a_timeout_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(ModelUnavailable):
        model(handler).complete(REQUEST)


def test_a_rejected_credential_is_raised_rather_than_retried() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(401, json={})

    with pytest.raises(Exception) as error:
        model(handler).complete(REQUEST)

    assert len(attempts) == 1
    assert not isinstance(error.value, ModelUnavailable)


def test_a_response_with_no_choices_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(ModelUnavailable):
        model(handler).complete(REQUEST)


def test_missing_usage_is_reported_as_absent_rather_than_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    response = model(handler).complete(REQUEST)

    assert response.usage.prompt_tokens is None
