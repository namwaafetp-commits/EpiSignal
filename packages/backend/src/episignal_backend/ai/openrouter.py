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
        payload = {
            "model": request.model_id,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "response_format": {"type": "json_object"},
        }
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
        for attempt in range(self._max_attempts):
            try:
                response = self._client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
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
                if response.status_code not in RETRY_STATUS:
                    response.raise_for_status()
                    body: dict[str, Any] = response.json()
                    return body
                last = str(response.status_code)

            if attempt + 1 < self._max_attempts:
                self._sleep(RETRY_DELAY_SECONDS)

        raise ModelUnavailable(last)


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
