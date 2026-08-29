import json
from collections.abc import Callable

import httpx
import pytest
from episignal_backend.ai.documents import ChatRequest
from episignal_backend.ai.gemini_batch import GeminiBatchClient
from episignal_backend.ai.protocol import ModelUnavailable

REQUESTS = [
    ChatRequest(model_id="google/gemini-2.5-flash-lite", system="s", user=f"article {i}")
    for i in range(2)
]


def result_entry(text: str) -> dict[str, object]:
    return {
        "response": {
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20},
        }
    }


class Router:
    """Answers by method and path so the poll cycle stays readable."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, object]] = {}
        self.results: dict[str, list[dict[str, object]]] = {}
        self.seen: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        path = request.url.path.split("/v1beta", 1)[-1]
        self.seen.append((method, path))
        if method == "POST" and path == "/batches":
            payload = json.loads(request.content)
            name = f"batches/{len(self.jobs) + 1}"
            self.jobs[name] = {"name": name, "state": "JOB_STATE_SUCCEEDED"}
            self.results[name] = [
                result_entry(json.dumps({"index": i})) for i in range(len(payload["requests"]))
            ]
            return httpx.Response(200, json=self.jobs[name])
        if method == "GET" and path.startswith("/batches/") and path.endswith("/results"):
            name = path.removesuffix("/results").lstrip("/")
            index = int(request.url.params["index"])
            return httpx.Response(200, json=self.results[name][index])
        if method == "GET" and path.startswith("/batches/"):
            name = path.lstrip("/")
            return httpx.Response(200, json=self.jobs[name])
        return httpx.Response(404, json={})


def client(router: Router, sleep: Callable[[float], None] = lambda s: None) -> GeminiBatchClient:
    return GeminiBatchClient(
        api_key="test-key",
        base_url="https://gemini.test/v1beta",
        client=httpx.Client(transport=httpx.MockTransport(router.handler)),
        sleep=sleep,
    )


def test_submit_creates_one_job_with_every_request_entry() -> None:
    router = Router()
    router.jobs.clear()

    class Inspect(Router):
        def handler(self, request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                body = json.loads(request.content)
                assert len(body["requests"]) == 2
                entry = body["requests"][0]
                assert entry["model"] == "models/gemini-2.5-flash-lite"
                assert entry["contents"][0]["parts"][0]["text"] == "article 0"
                assert entry["generation_config"]["response_mime_type"] == "application/json"
            return super().handler(request)

    name = client(Inspect()).submit(REQUESTS)

    assert name == "batches/1"


def test_poll_returns_answers_in_submission_order() -> None:
    router = Router()
    name = client(router).submit(REQUESTS)

    answers = client(router).poll(name, REQUESTS)

    assert [answer.content for answer in answers] == ['{"index": 0}', '{"index": 1}']
    assert all(answer.usage.prompt_tokens == 100 for answer in answers)


def test_a_pending_job_waits_until_its_budget_is_spent() -> None:
    router = Router()
    name = client(router).submit(REQUESTS)
    router.jobs[name] = {"name": name, "state": "JOB_STATE_RUNNING"}

    with pytest.raises(ModelUnavailable):
        client(router, sleep=lambda s: None).poll(name, REQUESTS, wait_seconds=0.0)


def test_a_failed_job_is_unavailable() -> None:
    router = Router()
    name = client(router).submit(REQUESTS)
    router.jobs[name] = {"name": name, "state": "JOB_STATE_FAILED"}

    with pytest.raises(ModelUnavailable):
        client(router).poll(name, REQUESTS)


def test_a_missing_entry_keeps_the_answers_the_job_did_give() -> None:
    router = Router()
    name = client(router).submit(REQUESTS)
    router.results[name][1] = {"error": {"code": 500}}

    answers = client(router).poll(name, REQUESTS)

    assert answers[0] is not None and answers[0].content == '{"index": 0}'
    assert answers[1] is None


def test_an_empty_submission_is_refused() -> None:
    with pytest.raises(ModelUnavailable):
        client(Router()).submit([])


def test_the_key_travels_as_a_header_never_as_a_query() -> None:
    router = Router()
    name = client(router).submit(REQUESTS)
    client(router).poll(name, REQUESTS)

    assert all("key" not in path for _, path in router.seen)
