"""The epidemiological extraction pass.

Extracts structured epidemiological facts from relevant news articles, one
signal at a time. Every extracted number and transmission flag is grounded in
the source text.

This module imports neither SQLAlchemy nor httpx.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from episignal_backend.ai.documents import (
    ChatRequest,
    ModelSpec,
    StoredExtraction,
)
from episignal_backend.ai.ladder import (
    Attempt,
    ClimbOutcome,
    Guards,
    Ladder,
    RunBudget,
    climb,
    cost_row,
)
from episignal_backend.ai.prompts import extraction_prompt
from episignal_backend.ai.protocol import AiRepository, ChatModel
from episignal_backend.ai.schema import Extraction
from episignal_backend.ai.validate import validate_extraction
from episignal_backend.db.types import AiPurpose

DEFAULT_LIMIT = 100
DEFAULT_MAX_TIER = 3
DEFAULT_MAX_INPUT_CHARACTERS = 12000
DEFAULT_MIN_CONFIDENCE = 0.5

logger = logging.getLogger("episignal_backend.ai.extract")


@dataclass(frozen=True)
class ExtractionResult:
    examined: int = 0
    extracted: int = 0
    reviewed: int = 0
    unavailable: int = 0
    requests: int = 0
    stopped_early: bool = False


def _request_builder(system: str, user: str) -> Callable[[ModelSpec], ChatRequest]:
    def _request(spec: ModelSpec) -> ChatRequest:
        return ChatRequest(model_id=spec.model_id, system=system, user=user)

    return _request


def _accept_builder(raw_text: str, min_confidence: float) -> Callable[[str], Extraction]:
    def _accept(content: str) -> Extraction:
        return validate_extraction(content, raw_text, min_confidence=min_confidence)

    return _accept


def run_extraction(
    repository: AiRepository,
    model: ChatModel,
    *,
    guards: Guards,
    limit: int = DEFAULT_LIMIT,
    max_tier: int = DEFAULT_MAX_TIER,
    max_input_characters: int = DEFAULT_MAX_INPUT_CHARACTERS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ExtractionResult:
    ladder = Ladder.build(repository.models(), max_tier=max_tier)
    budget = RunBudget(guards)
    pending = repository.awaiting_extraction(limit=limit)

    extracted = 0
    reviewed = 0
    unavailable = 0
    requests = 0
    stopped_early = False

    for signal in pending:
        system, user = extraction_prompt(signal, max_characters=max_input_characters)
        attempts: list[Attempt] = []

        result = climb(
            ladder=ladder,
            budget=budget,
            model=model,
            request_for=_request_builder(system, user),
            accept=_accept_builder(signal.raw_text, min_confidence),
            on_attempt=attempts.append,
        )
        requests += len(attempts)

        try:
            at = now()
            for attempt in attempts:
                repository.record_request(
                    cost_row(
                        attempt,
                        purpose=AiPurpose.EXTRACTION,
                        signal_id=signal.id,
                        batch_size=1,
                        at=at,
                    )
                )

            if result.outcome is ClimbOutcome.ACCEPTED and result.value is not None:
                disease_id = (
                    repository.resolve_disease(result.value.disease.name)
                    if result.value.disease
                    else None
                )
                repository.record_extraction(
                    signal.id,
                    StoredExtraction(
                        extraction=result.value,
                        disease_id=disease_id,
                        model_id=attempts[-1].spec.model_id,
                        processed_at=at,
                    ),
                )
                extracted += 1
            elif result.outcome is ClimbOutcome.REJECTED:
                repository.mark_needs_review(signal.id)
                reviewed += 1
            else:
                unavailable += 1

            repository.commit()
        except Exception as error:
            repository.rollback()
            logger.error(
                "Could not store extraction for signal %s (%s)", signal.id, type(error).__name__
            )

        if result.outcome is ClimbOutcome.GUARD:
            stopped_early = True
            break

    return ExtractionResult(
        examined=len(pending),
        extracted=extracted,
        reviewed=reviewed,
        unavailable=unavailable,
        requests=requests,
        stopped_early=stopped_early,
    )
