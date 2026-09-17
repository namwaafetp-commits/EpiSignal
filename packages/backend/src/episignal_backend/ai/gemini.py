"""Gemini `generateContent`, the Gemini rung of the ladder's adapter map.

Mirrors `openrouter.py`: the only other file in `ai/` that opens a socket,
one `complete` method on the `ChatModel` boundary, retries for the statuses a
busy endpoint returns, `ModelUnavailable` when nothing was learned, and a
schema-less JSON fallback when the provider rejects a schema it cannot hold.
The Gemini schema dialect accepts a subset of JSON Schema, so a Pydantic
schema is sanitized before it is sent: references are inlined, optional
unions become nullable, and fields the dialect rejects are dropped rather
than trusted to be ignored.
"""

import time
from collections.abc import Callable
from time import sleep as default_sleep
from typing import Any

import httpx

from episignal_backend.ai.documents import ChatRequest, ChatResponse, TokenUsage
from episignal_backend.ai.protocol import ModelUnavailable

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT_SECONDS = 60.0
MAX_ATTEMPTS = 3
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
RETRY_DELAY_SECONDS = 2.0

# What the Gemini response-schema dialect is known to accept. Everything else
# a Pydantic schema carries is dropped before the wire, because the endpoint
# rejects unknown fields instead of ignoring them.
_SUPPORTED_SCHEMA_KEYS = frozenset(
    {"type", "format", "description", "nullable", "enum", "items", "properties", "required"}
)

_REF_PREFIX = "#/$defs/"


class CredentialRejected(Exception):
    """The key was refused. Nothing about this run will improve by asking again."""


def native_model_id(model_id: str) -> str:
    """The roster speaks OpenRouter-style ids; the native API does not."""
    return model_id.removeprefix("google/")


def sanitize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a JSON Schema into the subset the Gemini dialect accepts."""
    sanitized = _sanitize(schema, schema.get("$defs", {}))
    return sanitized if isinstance(sanitized, dict) else {}


def _sanitize(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_sanitize(item, defs) for item in node]
    if not isinstance(node, dict):
        return node

    reference = node.get("$ref")
    if isinstance(reference, str) and reference.startswith(_REF_PREFIX):
        target = defs.get(reference.removeprefix(_REF_PREFIX))
        if isinstance(target, dict):
            return _sanitize(target, defs)

    if "anyOf" in node:
        members = [_sanitize(member, defs) for member in node["anyOf"]]
        non_null = [member for member in members if member.get("type") != "null"]
        if len(non_null) == 1 and len(members) == 2:
            merged = dict(non_null[0])
            merged["nullable"] = True
            return {key: value for key, value in merged.items() if key in _SUPPORTED_SCHEMA_KEYS}
        return {"nullable": True} if not non_null else non_null[0]

    result: dict[str, Any] = {}
    for key, value in node.items():
        if key not in _SUPPORTED_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            # Property names are not schema keywords; their values are schemas.
            result[key] = {name: _sanitize(sub, defs) for name, sub in value.items()}
        else:
            result[key] = _sanitize(value, defs)
    return result


class GeminiChatModel:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = default_sleep,
        timeout_seconds: float = TIMEOUT_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._sleep = sleep
        self._max_attempts = max_attempts

    def complete(self, request: ChatRequest) -> ChatResponse:
        payload: dict[str, Any] = {
            "system_instruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": [{"text": request.user}]}],
            "generation_config": {"response_mime_type": "application/json"},
        }
        if request.temperature is not None:
            payload["generation_config"]["temperature"] = request.temperature
        if request.response_schema is not None:
            payload["generation_config"]["response_schema"] = sanitize_schema(
                request.response_schema
            )

        started = time.monotonic()
        response = self._post(request.model_id, payload)
        latency_ms = int((time.monotonic() - started) * 1000)

        return ChatResponse(
            content=_content(response),
            usage=_usage(response),
            http_status=200,
            latency_ms=latency_ms,
        )

    def _post(self, model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        last = ""
        last_status: int | None = None
        current_payload = dict(payload)
        for attempt in range(self._max_attempts):
            try:
                response = self._client.post(
                    f"{self._base_url}/models/{native_model_id(model_id)}:generateContent",
                    json=current_payload,
                    headers={
                        "x-goog-api-key": self._api_key,
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as error:
                last = type(error).__name__
            else:
                if response.status_code in {401, 403}:
                    raise CredentialRejected(f"Gemini refused the key ({response.status_code})")
                if response.status_code == 400:
                    generation = current_payload.get("generation_config")
                    if isinstance(generation, dict) and "response_schema" in generation:
                        del generation["response_schema"]
                        continue
                if response.status_code not in RETRY_STATUS:
                    response.raise_for_status()
                    body: dict[str, Any] = response.json()
                    return body
                last = str(response.status_code)
                last_status = response.status_code

            if attempt + 1 < self._max_attempts:
                self._sleep(RETRY_DELAY_SECONDS)

        raise ModelUnavailable(last, attempts=self._max_attempts, http_status=last_status)


def _content(body: dict[str, Any]) -> str:
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        # A refusal arrives as an absent candidate, and a blocked one as a
        # finish reason. Either way nothing was learned about the signal.
        raise ModelUnavailable("no candidates in the response")
    first = candidates[0]
    finish = first.get("finishReason") if isinstance(first, dict) else None
    if finish in {"SAFETY", "RECITATION", "BLOCKLIST"}:
        raise ModelUnavailable(f"finish reason {finish}")
    content = first.get("content") if isinstance(first, dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        raise ModelUnavailable("no content parts in the response")
    texts = [part.get("text") for part in parts if isinstance(part, dict)]
    joined = "".join(text for text in texts if isinstance(text, str))
    if not joined:
        raise ModelUnavailable("no text in the content parts")
    return joined


def _usage(body: dict[str, Any]) -> TokenUsage:
    # Absent rather than zero, for the same reason as every other adapter: a
    # ledger that records a call as free when the provider did not say is a
    # ledger that understates the truth.
    usage = body.get("usageMetadata")
    if not isinstance(usage, dict):
        return TokenUsage()
    prompt = usage.get("promptTokenCount")
    completion = usage.get("candidatesTokenCount")
    return TokenUsage(
        prompt_tokens=prompt if isinstance(prompt, int) else None,
        completion_tokens=completion if isinstance(completion, int) else None,
    )
