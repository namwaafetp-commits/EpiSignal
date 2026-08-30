"""The batched relevance pass.

Batched because relevance is decided from a title and an opening, and one
request can carry many of those. The batch is also the unit of trust: an answer
that does not address exactly the batch it was given is discarded whole.

This module imports neither SQLAlchemy nor httpx.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from episignal_backend.ai.documents import (
    ChatRequest,
    ClassifiableSignal,
    ModelSpec,
    Verdict,
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
from episignal_backend.ai.prompts import classification_prompt
from episignal_backend.ai.protocol import AiRepository, ChatModel
from episignal_backend.ai.schema import ClassificationResponse
from episignal_backend.ai.validate import validate_classification
from episignal_backend.db.types import AiPurpose, ReviewReason

DEFAULT_BATCH_SIZE = 20
DEFAULT_LIMIT = 100
DEFAULT_MAX_TIER = 3

logger = logging.getLogger("episignal_backend.ai.classify")


@dataclass(frozen=True)
class ClassificationResult:
    examined: int = 0
    relevant: int = 0
    irrelevant: int = 0
    reviewed: int = 0
    # Signals no tier could be asked about. Not failures and not decisions:
    # they are simply still waiting.
    unavailable: int = 0
    requests: int = 0
    stopped_early: bool = False


def _batches(
    pending: Sequence[ClassifiableSignal], size: int
) -> list[Sequence[ClassifiableSignal]]:
    return [pending[start : start + size] for start in range(0, len(pending), size)]


def _request_builder(system: str, user: str) -> Callable[[ModelSpec], ChatRequest]:
    def _request(spec: ModelSpec) -> ChatRequest:
        return ChatRequest(model_id=spec.model_id, system=system, user=user)

    return _request


def _accept_builder(identifiers: Sequence[UUID]) -> Callable[[str], ClassificationResponse]:
    def _accept(content: str) -> ClassificationResponse:
        return validate_classification(content, identifiers)

    return _accept


def run_classification(
    repository: AiRepository,
    model: ChatModel,
    *,
    guards: Guards,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int = DEFAULT_LIMIT,
    max_tier: int = DEFAULT_MAX_TIER,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ClassificationResult:
    ladder = Ladder.build(repository.models(), max_tier=max_tier)
    budget = RunBudget(guards)
    pending = repository.awaiting_classification(limit=limit)

    relevant = 0
    irrelevant = 0
    reviewed = 0
    unavailable = 0
    requests = 0
    stopped_early = False

    for batch in _batches(pending, batch_size):
        identifiers = [signal.id for signal in batch]
        system, user = classification_prompt(batch)
        attempts: list[Attempt] = []

        result = climb(
            ladder=ladder,
            budget=budget,
            model=model,
            request_for=_request_builder(system, user),
            accept=_accept_builder(identifiers),
            on_attempt=attempts.append,
        )
        requests += len(attempts)

        try:
            at = now()
            for attempt in attempts:
                repository.record_request(
                    cost_row(
                        attempt,
                        purpose=AiPurpose.CLASSIFICATION,
                        signal_id=None,
                        batch_size=len(batch),
                        at=at,
                    )
                )

            if result.outcome is ClimbOutcome.ACCEPTED and result.value is not None:
                # The accepted answer is always the last attempt, which is the
                # rung whose name belongs on every signal it decided.
                decided = _write(repository, result.value, attempts[-1].spec.model_id, at)
                relevant += decided
                irrelevant += len(batch) - decided
            elif result.outcome is ClimbOutcome.REJECTED:
                for signal in batch:
                    repository.open_review(signal.id, reason=ReviewReason.EXTRACTION_REJECTED)
                reviewed += len(batch)
            else:
                # GUARD or UNAVAILABLE: nothing was learned about these signals,
                # so nothing is written about them and the next run sees them
                # unchanged. The cost rows above are still committed, because
                # the attempt itself is a fact.
                unavailable += len(batch)

            repository.commit()
        except Exception as error:
            repository.rollback()
            logger.error("Could not store a classification batch (%s)", type(error).__name__)

        if result.outcome is ClimbOutcome.GUARD:
            stopped_early = True
            break

    return ClassificationResult(
        examined=len(pending),
        relevant=relevant,
        irrelevant=irrelevant,
        reviewed=reviewed,
        unavailable=unavailable,
        requests=requests,
        stopped_early=stopped_early,
    )


def _write(
    repository: AiRepository, response: ClassificationResponse, model_id: str, at: datetime
) -> int:
    relevant = 0
    for entry in response.results:
        repository.record_classification(
            entry.id,
            Verdict(
                is_public_health_relevant=entry.is_public_health_relevant,
                signal_type=entry.signal_type,
                relevance=entry.relevance,
                model_id=model_id,
                decided_at=at,
            ),
        )
        relevant += 1 if entry.is_public_health_relevant else 0
    return relevant
