"""DeepSeek relevance pass over discovery metadata."""

import logging
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from episignal_backend.ai.documents import ChatRequest, ModelSpec, Verdict
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
from episignal_backend.ai.registry import model_for_purpose
from episignal_backend.ai.schema import ClassificationVerdict, classification_json_schema
from episignal_backend.ai.validate import validate_classification
from episignal_backend.db.types import AiPurpose, SignalType
from episignal_backend.diagnostics import classify_ai_failure

CLASSIFICATION_SCHEMA_NAME = "relevance_response"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClassificationResult:
    examined: int = 0
    relevant: int = 0
    irrelevant: int = 0
    reviewed: int = 0
    unavailable: int = 0
    requests: int = 0
    stopped_early: bool = False
    failure_categories: Mapping[str, int] = field(default_factory=dict)


def run_classification(
    repository: AiRepository,
    model: ChatModel,
    *,
    guards: Guards,
    limit: int = 100,
    batch_size: int = 1,
    max_tier: int = 3,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    signal_ids: Sequence[UUID] | None = None,
) -> ClassificationResult:
    """Ask DeepSeek once per sighting; no disease/location extraction here."""
    del batch_size, max_tier
    specs = repository.models()
    spec = model_for_purpose(specs, AiPurpose.CLASSIFICATION)
    ladder = Ladder(rungs=(spec,))
    budget = RunBudget(guards)
    if signal_ids is None:
        pending = repository.awaiting_classification(limit=limit)
    else:
        pending = repository.awaiting_classification(limit=limit, signal_ids=signal_ids)
    relevant = irrelevant = reviewed = unavailable = requests = 0
    failure_categories: Counter[str] = Counter()
    stopped_early = False

    for signal in pending:
        system, user = classification_prompt(signal)
        attempts: list[Attempt] = []

        def request_for(_: ModelSpec, *, system: str = system, user: str = user) -> ChatRequest:
            return ChatRequest(
                model_id=spec.model_id,
                system=system,
                user=user,
                response_schema=classification_json_schema(),
                schema_name=CLASSIFICATION_SCHEMA_NAME,
                temperature=0.0,
            )

        result = climb(
            ladder=ladder,
            budget=budget,
            model=model,
            request_for=request_for,
            accept=validate_classification,
            on_attempt=attempts.append,
        )
        requests += len(attempts)
        for attempt in attempts:
            if attempt.outcome.value != "accepted":
                failure_categories[
                    classify_ai_failure(
                        attempt.reason,
                        http_status=attempt.http_status,
                        rejected=attempt.outcome.value == "rejected",
                    ).value
                ] += 1
        at = now()
        try:
            for attempt in attempts:
                repository.record_request(
                    cost_row(
                        attempt,
                        purpose=AiPurpose.CLASSIFICATION,
                        signal_id=signal.id,
                        batch_size=1,
                        at=at,
                    )
                )
            if result.outcome is ClimbOutcome.ACCEPTED and isinstance(
                result.value, ClassificationVerdict
            ):
                repository.record_classification(
                    signal.id,
                    Verdict(
                        is_public_health_relevant=result.value.relevant,
                        signal_type=SignalType.UNKNOWN,
                        relevance=result.value.confidence,
                        model_id=spec.model_id,
                        decided_at=at,
                    ),
                )
            elif result.outcome is ClimbOutcome.REJECTED:
                pass
            else:
                pass
            repository.commit()
            if result.outcome is ClimbOutcome.ACCEPTED and isinstance(
                result.value, ClassificationVerdict
            ):
                relevant += int(result.value.relevant)
                irrelevant += int(not result.value.relevant)
            elif result.outcome is ClimbOutcome.REJECTED:
                reviewed += 1
            else:
                unavailable += 1
        except Exception:
            repository.rollback()
            reviewed += 1
            logger.error("classification storage failed for signal %s", signal.id, exc_info=True)
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
        failure_categories=dict(failure_categories),
    )


def _write(
    repository: AiRepository,
    response: ClassificationVerdict,
    model_id: str,
    at: datetime,
    signal_id: UUID,
) -> int:
    repository.record_classification(
        signal_id,
        Verdict(
            is_public_health_relevant=response.relevant,
            signal_type=SignalType.UNKNOWN,
            relevance=response.confidence,
            model_id=model_id,
            decided_at=at,
        ),
    )
    return int(response.relevant)
