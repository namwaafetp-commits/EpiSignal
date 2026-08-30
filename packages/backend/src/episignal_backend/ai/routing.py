"""One `ChatModel` that answers through whichever adapter a rung names.

The ladder protocol was built so one adapter serves the whole ladder; a
provider column breaks that assumption without changing the protocol, so the
runner hands the passes one routed model instead of teaching the ladder about
adapters. Routing happens by model id, because that is the only fact a
`ChatRequest` carries.
"""

from collections.abc import Mapping

from episignal_backend.ai.documents import ChatRequest, ChatResponse, ModelSpec
from episignal_backend.ai.gemini import GeminiChatModel
from episignal_backend.ai.openrouter import OpenRouterChatModel
from episignal_backend.ai.protocol import ChatModel, ModelUnavailable
from episignal_backend.config import Settings
from episignal_backend.db.types import AiProvider


class NoProviderKey(Exception):
    """No provider key is configured, so there is no ladder to serve."""


def build_adapters(
    *,
    openrouter_api_key: str | None,
    gemini_api_key: str | None,
    openrouter_base_url: str,
    gemini_base_url: str,
    timeout_seconds: float,
    max_attempts: int,
) -> dict[AiProvider, ChatModel]:
    """One adapter per provider whose key is configured.

    A provider without a key contributes nothing: its rungs answer
    `ModelUnavailable` at climb time, which is the ladder's existing way of
    saying a rung could not be asked.
    """
    adapters: dict[AiProvider, ChatModel] = {}
    if openrouter_api_key is not None:
        adapters[AiProvider.OPENROUTER] = OpenRouterChatModel(
            openrouter_api_key,
            base_url=openrouter_base_url,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
    if gemini_api_key is not None:
        adapters[AiProvider.GEMINI] = GeminiChatModel(
            gemini_api_key,
            base_url=gemini_base_url,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
    if not adapters:
        raise NoProviderKey(
            "neither EPISIGNAL_OPENROUTER_API_KEY nor EPISIGNAL_GEMINI_API_KEY is set"
        )
    return adapters


class RoutedChatModel:
    """Dispatches `complete` to the adapter a roster row named."""

    def __init__(self, routes: Mapping[str, ChatModel]) -> None:
        self._routes = dict(routes)

    @classmethod
    def from_specs(
        cls, specs: list[ModelSpec], adapters: Mapping[AiProvider, ChatModel]
    ) -> "RoutedChatModel":
        # A rung whose provider has no adapter is left unlisted on purpose: an
        # unroutable rung is unavailable, and the ladder already knows what to
        # do with an unavailable rung.
        routes = {
            spec.model_id: adapters[spec.provider] for spec in specs if spec.provider in adapters
        }
        return cls(routes)

    def complete(self, request: ChatRequest) -> ChatResponse:
        adapter = self._routes.get(request.model_id)
        if adapter is None:
            raise ModelUnavailable(f"no adapter for {request.model_id}")
        return adapter.complete(request)


def routed_from_settings(settings: Settings, specs: list[ModelSpec]) -> RoutedChatModel:
    """One construction shared by the manual runner and the scheduled stage.

    Raises `NoProviderKey` when neither provider key is configured; callers
    decide whether that is fatal (extraction) or a degraded run (the delta
    pass inside event assembly).
    """
    adapters = build_adapters(
        openrouter_api_key=(
            settings.openrouter_api_key.get_secret_value() if settings.openrouter_api_key else None
        ),
        gemini_api_key=(
            settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
        ),
        openrouter_base_url=settings.openrouter_base_url,
        gemini_base_url=settings.gemini_base_url,
        timeout_seconds=settings.ai_request_timeout_seconds,
        max_attempts=settings.ai_max_attempts_per_tier,
    )
    return RoutedChatModel.from_specs(specs, adapters)
