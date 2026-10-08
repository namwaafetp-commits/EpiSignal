"""OpenRouter chat completions, the only file in `ai/` that opens a socket.

One adapter serves the whole ladder: a tier is a model id and a price, not a
protocol. Retries cover the statuses a free endpoint returns when it is busy;
everything else is raised, because retrying a rejected credential only spends
the run's request budget on a problem that will not fix itself.
"""

import time
from collections.abc import Callable
from time import sleep as default_sleep
from typing import Any

import httpx

from episignal_backend.ai.documents import ChatRequest, ChatResponse, TokenUsage
from episignal_backend.ai.protocol import ModelUnavailable

BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SECONDS = 60.0
MAX_ATTEMPTS = 3
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
RETRY_DELAY_SECONDS = 2.0


class CredentialRejected(Exception):
    """The key was refused. Nothing about this run will improve by asking again."""


def supports_structured_outputs(model_id: str) -> bool:
    """Whether a model ID is known to support OpenRouter json_schema structured outputs."""
    normalized = model_id.strip().lower()
    if normalized.endswith(":free") or ":free" in normalized or "claude-3-haiku" in normalized:
        return False
    supported_prefixes_or_terms = (
        "deepseek/",
        "anthropic/claude-haiku-4",
        "anthropic/claude-3.5-haiku",
        "anthropic/claude-3.5-sonnet",
        "anthropic/claude-3-7-sonnet",
        "anthropic/claude-haiku-latest",
        "mistralai/mistral-small-24b",
        "mistralai/mistral-small-2603",
        "mistralai/mistral-large",
        "openai/",
        "google/gemini-2",
        "google/gemini-1.5",
        "qwen/qwen-2.5",
    )
    return any(term in normalized for term in supported_prefixes_or_terms)


class OpenRouterChatModel:
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
            "model": request.model_id,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        if request.response_schema is not None and supports_structured_outputs(request.model_id):
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name or "response_schema",
                    "strict": True,
                    "schema": request.response_schema,
                },
            }
        else:
            payload["response_format"] = {"type": "json_object"}

        started = time.monotonic()
        response = self._post(payload)
        latency_ms = int((time.monotonic() - started) * 1000)

        return ChatResponse(
            content=_content(response),
            usage=_usage(response),
            http_status=200,
            latency_ms=latency_ms,
        )

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        last = ""
        last_status: int | None = None
        current_payload = dict(payload)
        for attempt in range(self._max_attempts):
            try:
                response = self._client.post(
                    f"{self._base_url}/chat/completions",
                    json=current_payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as error:
                last = type(error).__name__
            else:
                if response.status_code in {401, 403}:
                    raise CredentialRejected(f"OpenRouter refused the key ({response.status_code})")
                if response.status_code == 400:
                    resp_format = current_payload.get("response_format")
                    if isinstance(resp_format, dict) and resp_format.get("type") == "json_schema":
                        current_payload["response_format"] = {"type": "json_object"}
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
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelUnavailable("no choices in the response")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ModelUnavailable("no message content in the response")
    return content


def _usage(body: dict[str, Any]) -> TokenUsage:
    # Absent rather than zero: a ledger that records a call as free when the
    # provider simply did not say is a ledger that understates the truth.
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return TokenUsage()
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    return TokenUsage(
        prompt_tokens=prompt if isinstance(prompt, int) else None,
        completion_tokens=completion if isinstance(completion, int) else None,
    )
