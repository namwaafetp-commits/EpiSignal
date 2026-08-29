from uuid import uuid4

import pytest
from episignal_backend.ai.documents import ChatRequest, ChatResponse, ModelSpec
from episignal_backend.ai.gemini import GeminiChatModel
from episignal_backend.ai.openrouter import OpenRouterChatModel
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.ai.routing import NoProviderKey, RoutedChatModel, build_adapters
from episignal_backend.db.types import AiProvider

ADAPTER_ARGS = {
    "openrouter_base_url": "https://openrouter.test/api/v1",
    "gemini_base_url": "https://gemini.test/v1beta",
    "timeout_seconds": 5.0,
    "max_attempts": 2,
}


def spec(provider: AiProvider, model_id: str = "vendor/model", tier: int = 1) -> ModelSpec:
    return ModelSpec(
        id=uuid4(),
        tier=tier,
        model_id=model_id,
        label=model_id,
        provider=provider,
        prompt_price_per_million="0.10",
        completion_price_per_million="0.40",
    )


def test_build_adapters_skips_providers_without_keys() -> None:
    adapters = build_adapters(
        openrouter_api_key="or-key",
        gemini_api_key=None,
        **ADAPTER_ARGS,  # type: ignore[arg-type]
    )

    assert set(adapters) == {AiProvider.OPENROUTER}
    assert isinstance(adapters[AiProvider.OPENROUTER], OpenRouterChatModel)


def test_build_adapters_serves_both_providers_when_both_keys_exist() -> None:
    adapters = build_adapters(
        openrouter_api_key="or-key",
        gemini_api_key="g-key",
        **ADAPTER_ARGS,  # type: ignore[arg-type]
    )

    assert set(adapters) == {AiProvider.OPENROUTER, AiProvider.GEMINI}
    assert isinstance(adapters[AiProvider.GEMINI], GeminiChatModel)


def test_build_adapters_refuses_a_keyless_run() -> None:
    with pytest.raises(NoProviderKey):
        build_adapters(
            openrouter_api_key=None,
            gemini_api_key=None,
            **ADAPTER_ARGS,  # type: ignore[arg-type]
        )


class FakeAdapter:
    def __init__(self) -> None:
        self.asked: list[str] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.asked.append(request.model_id)
        return ChatResponse(content="{}", latency_ms=1)


def test_routed_model_dispatches_each_rung_to_its_provider_adapter() -> None:
    gemini = FakeAdapter()
    openrouter = FakeAdapter()
    routed = RoutedChatModel.from_specs(
        [
            spec(AiProvider.GEMINI, "google/gemini-2.5-flash-lite", tier=1),
            spec(AiProvider.OPENROUTER, "mistralai/mistral-small", tier=2),
        ],
        {AiProvider.GEMINI: gemini, AiProvider.OPENROUTER: openrouter},
    )

    routed.complete(ChatRequest(model_id="google/gemini-2.5-flash-lite", system="s", user="u"))
    routed.complete(ChatRequest(model_id="mistralai/mistral-small", system="s", user="u"))

    assert gemini.asked == ["google/gemini-2.5-flash-lite"]
    assert openrouter.asked == ["mistralai/mistral-small"]


def test_a_rung_whose_provider_has_no_adapter_is_unavailable() -> None:
    openrouter = FakeAdapter()
    routed = RoutedChatModel.from_specs(
        [
            spec(AiProvider.GEMINI, "google/gemini-2.5-flash-lite", tier=1),
            spec(AiProvider.OPENROUTER, "mistralai/mistral-small", tier=2),
        ],
        {AiProvider.OPENROUTER: openrouter},
    )

    with pytest.raises(ModelUnavailable):
        routed.complete(ChatRequest(model_id="google/gemini-2.5-flash-lite", system="s", user="u"))


def test_an_unknown_model_id_is_unavailable() -> None:
    routed = RoutedChatModel.from_specs([], {})

    with pytest.raises(ModelUnavailable):
        routed.complete(ChatRequest(model_id="anything", system="s", user="u"))
