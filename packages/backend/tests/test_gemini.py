import json

import httpx
import pytest
from episignal_backend.ai.documents import ChatRequest
from episignal_backend.ai.gemini import GeminiChatModel, native_model_id, sanitize_schema
from episignal_backend.ai.protocol import ModelUnavailable

REQUEST = ChatRequest(model_id="google/gemini-2.5-flash-lite", system="rules", user="article")


def model(handler: object, sleeps: list[float] | None = None) -> GeminiChatModel:
    client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return GeminiChatModel(
        api_key="test-key",
        client=client,
        sleep=sleeps.append if sleeps is not None else (lambda s: None),
    )


def body(text: str, prompt: int = 900, completion: int = 120) -> dict[str, object]:
    return {
        "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}],
        "usageMetadata": {"promptTokenCount": prompt, "candidatesTokenCount": completion},
    }


def test_a_successful_call_returns_the_content_and_the_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body('{"ok": true}'))

    response = model(handler).complete(REQUEST)

    assert response.content == '{"ok": true}'
    assert response.usage.prompt_tokens == 900
    assert response.usage.completion_tokens == 120
    assert response.http_status == 200
    assert response.latency_ms >= 0


def test_the_request_targets_the_native_model_and_carries_the_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body("{}"))

    model(handler).complete(REQUEST)

    assert seen[0].url.path.endswith("/models/gemini-2.5-flash-lite:generateContent")
    assert seen[0].headers["x-goog-api-key"] == "test-key"


def test_the_request_carries_system_contents_and_generation_config() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=body("{}"))

    request = ChatRequest(
        model_id="google/gemini-2.5-flash-lite",
        system="rules",
        user="article",
        response_schema={"type": "object", "properties": {"cases": {"type": "integer"}}},
        schema_name="extraction_response",
        temperature=0.0,
    )
    model(handler).complete(request)

    payload = seen[0]
    assert payload["system_instruction"] == {"parts": [{"text": "rules"}]}
    assert payload["contents"] == [{"role": "user", "parts": [{"text": "article"}]}]
    config = payload["generation_config"]
    assert config["response_mime_type"] == "application/json"
    assert config["temperature"] == 0.0
    assert config["response_schema"] == {
        "type": "object",
        "properties": {"cases": {"type": "integer"}},
    }


def test_the_schema_is_sanitized_for_the_gemini_dialect() -> None:
    sanitized = sanitize_schema(
        {
            "title": "Extraction",
            "type": "object",
            "additionalProperties": False,
            "required": ["disease"],
            "properties": {
                "disease": {"$ref": "#/$defs/Disease"},
                "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
            "$defs": {
                "Disease": {
                    "title": "D",
                    "type": "string",
                    "enum": ["cholera", "measles"],
                }
            },
        }
    )

    assert sanitized == {
        "type": "object",
        "required": ["disease"],
        "properties": {
            "disease": {"type": "string", "enum": ["cholera", "measles"]},
            "note": {"type": "string", "nullable": True},
        },
    }


def test_a_rejected_schema_falls_back_to_plain_json_mode() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            return httpx.Response(400, json={"error": {"code": 400}})
        return httpx.Response(200, json=body("{}"))

    request = ChatRequest(
        model_id="google/gemini-2.5-flash-lite",
        system="rules",
        user="article",
        response_schema={"type": "object"},
    )
    model(handler).complete(request)

    assert "response_schema" in seen[0]["generation_config"]
    assert "response_schema" not in seen[1]["generation_config"]
    assert seen[1]["generation_config"]["response_mime_type"] == "application/json"


def test_a_retryable_status_then_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if getattr(handler, "called", False):  # type: ignore[attr-defined]
            return httpx.Response(200, json=body("{}"))
        handler.called = True  # type: ignore[attr-defined]
        return httpx.Response(429)

    assert model(handler).complete(REQUEST).content == "{}"


def test_exhausted_retries_raise_model_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(ModelUnavailable):
        model(handler).complete(REQUEST)


def test_a_refused_key_is_not_retried() -> None:
    from episignal_backend.ai.gemini import CredentialRejected

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    with pytest.raises(CredentialRejected):
        model(handler).complete(REQUEST)


def test_a_safety_block_is_model_unavailable() -> None:
    blocked = {
        "candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=blocked)

    with pytest.raises(ModelUnavailable):
        model(handler).complete(REQUEST)


def test_no_candidates_is_model_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with pytest.raises(ModelUnavailable):
        model(handler).complete(REQUEST)


def test_native_model_id_strips_the_vendor_prefix() -> None:
    assert native_model_id("google/gemini-2.5-flash-lite") == "gemini-2.5-flash-lite"
    assert native_model_id("gemini-2.5-flash-lite") == "gemini-2.5-flash-lite"
