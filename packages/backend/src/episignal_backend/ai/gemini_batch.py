"""Gemini batch processing: submit many, poll once, answer per request.

The batch path exists for the scheduled extraction runs, where a fifty-percent
discount is worth an asynchronous cycle. One job carries every request a run
collected; a later poll retrieves the answers. A request whose answer never
arrives — the job was rejected, expired its wait budget, or came back without
that entry — surfaces as `ModelUnavailable`, so the caller re-selects it for
real-time exactly as it would after any other unavailable rung.

Endpoint shapes follow the v1beta batch API: create a job under `/batches`,
read it back by name until `state` is done, then fetch each entry's result
under `/batches/{name}/results?index=N`. Only this module knows that; the
caller sees `submit` and `poll`.
"""

import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from episignal_backend.ai.documents import ChatRequest, ChatResponse, TokenUsage
from episignal_backend.ai.gemini import native_model_id, sanitize_schema
from episignal_backend.ai.protocol import ModelUnavailable

TIMEOUT_SECONDS = 60.0
DONE_STATES = frozenset({"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED"})
FAILED_STATES = frozenset({"JOB_STATE_FAILED", "JOB_STATE_CANCELLED"})


class GeminiBatchClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = lambda seconds: None,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._sleep = sleep

    def submit(self, requests: Sequence[ChatRequest]) -> str:
        """Create one batch job and return its resource name."""
        if not requests:
            raise ModelUnavailable("an empty batch cannot be submitted")
        payload = {"requests": [_entry(request) for request in requests]}
        response = self._request("POST", "/batches", json=payload)
        name = response.get("name")
        if not isinstance(name, str) or not name:
            raise ModelUnavailable("the batch job was created without a name")
        return name

    def poll(
        self,
        name: str,
        requests: Sequence[ChatRequest],
        *,
        wait_seconds: float = 0.0,
    ) -> list[ChatResponse]:
        """Wait for the job, then return one answer per submitted request.

        Answers arrive in submission order. An entry the job never answered is
        `None` in the raw list and becomes `ModelUnavailable` here, so a partial
        batch costs its caller nothing but a real-time retry of the gap.
        """
        deadline = time.monotonic() + wait_seconds
        while True:
            job = self._request("GET", f"/{name}")
            state = job.get("state")
            if state in DONE_STATES:
                break
            if time.monotonic() >= deadline:
                raise ModelUnavailable(f"batch job still {state}")
            self._sleep(5.0)
        if job.get("state") in FAILED_STATES:
            raise ModelUnavailable(f"batch job ended {job.get('state')}")

        answers: list[ChatResponse | None] = [None] * len(requests)
        for index in range(len(requests)):
            entry = self._request("GET", f"/{name}/results", params={"index": str(index)})
            response = _answer(entry)
            if response is not None:
                answers[index] = response
        missing = [i for i, answer in enumerate(answers) if answer is None]
        if missing:
            raise ModelUnavailable(f"batch answers missing for {len(missing)} requests")
        return [answer for answer in answers if answer is not None]

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(
                method,
                f"{self._base_url}{path}",
                headers={"x-goog-api-key": self._api_key},
                **kwargs,
            )
        except httpx.HTTPError as error:
            raise ModelUnavailable(type(error).__name__) from error
        if response.status_code in {401, 403}:
            raise ModelUnavailable("the batch API refused the key")
        if response.status_code >= 400:
            raise ModelUnavailable(f"batch API returned {response.status_code}")
        try:
            payload = response.json()
        except ValueError as error:
            raise ModelUnavailable("the batch API answered without JSON") from error
        return payload if isinstance(payload, dict) else {}


def _entry(request: ChatRequest) -> dict[str, Any]:
    generation: dict[str, Any] = {"response_mime_type": "application/json"}
    if request.temperature is not None:
        generation["temperature"] = request.temperature
    if request.response_schema is not None:
        generation["response_schema"] = sanitize_schema(request.response_schema)
    return {
        "model": f"models/{native_model_id(request.model_id)}",
        "system_instruction": {"parts": [{"text": request.system}]},
        "contents": [{"role": "user", "parts": [{"text": request.user}]}],
        "generation_config": generation,
    }


def _answer(entry: dict[str, Any]) -> ChatResponse | None:
    # A result entry wraps the same `candidates` shape `generateContent`
    # returns, plus the job's own error field for a request the job dropped.
    if isinstance(entry.get("error"), dict):
        return None
    response = entry.get("response")
    if not isinstance(response, dict):
        return None
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    first = candidates[0]
    content = first.get("content") if isinstance(first, dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        return None
    texts = [part.get("text") for part in parts if isinstance(part, dict)]
    joined = "".join(text for text in texts if isinstance(text, str))
    if not joined:
        return None
    usage = response.get("usageMetadata")
    prompt = usage.get("promptTokenCount") if isinstance(usage, dict) else None
    completion = usage.get("candidatesTokenCount") if isinstance(usage, dict) else None
    return ChatResponse(
        content=joined,
        usage=TokenUsage(
            prompt_tokens=prompt if isinstance(prompt, int) else None,
            completion_tokens=completion if isinstance(completion, int) else None,
        ),
        http_status=200,
        latency_ms=0,
    )
