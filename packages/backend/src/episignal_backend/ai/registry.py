"""Purpose-specific production model selection.

Model rows remain database-owned. This module names the required route for each
active AI purpose and validates that a supplied row matches both model and
provider. Business passes ask for a purpose, never a provider/model literal.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.ai.documents import ModelSpec
from episignal_backend.ai.protocol import NoModelsConfigured
from episignal_backend.db.types import AiProvider, AiPurpose


@dataclass(frozen=True)
class PurposeRoute:
    model_id: str
    provider: AiProvider


PURPOSE_ROUTES: dict[AiPurpose, PurposeRoute] = {
    AiPurpose.CLASSIFICATION: PurposeRoute(
        model_id="deepseek/deepseek-v4-flash-0731",
        provider=AiProvider.OPENROUTER,
    ),
    AiPurpose.EXTRACTION: PurposeRoute(
        model_id="google/gemini-3.1-flash-lite",
        provider=AiProvider.GEMINI,
    ),
    AiPurpose.EVENT_SUMMARY: PurposeRoute(
        model_id="mistralai/mistral-small-3.2-24b-instruct",
        provider=AiProvider.OPENROUTER,
    ),
}


def model_for_purpose(specs: Sequence[ModelSpec], purpose: AiPurpose) -> ModelSpec:
    """Return the one configured row allowed to serve ``purpose``."""
    route = PURPOSE_ROUTES.get(purpose)
    if route is None:
        raise NoModelsConfigured(f"no production route for {purpose.value}")
    matches: list[ModelSpec] = [
        spec
        for spec in specs
        if spec.model_id == route.model_id
        and spec.provider is route.provider
        and (spec.purpose is None or spec.purpose is purpose)
    ]
    if len(matches) != 1:
        raise NoModelsConfigured(
            f"production route {purpose.value} requires {route.provider.value}:{route.model_id}"
        )
    return matches[0]
