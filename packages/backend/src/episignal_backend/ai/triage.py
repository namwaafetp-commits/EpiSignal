"""Early structured metadata from one signal's title and opening paragraph.

One accepted verdict supplies candidate blocking before extraction. A malformed
answer gets one repair prompt; a second malformed answer becomes an explicit
failed triage state while leaving the signal available to extraction.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError

from episignal_backend.ai.documents import ChatRequest, ModelSpec, TriageableSignal
from episignal_backend.ai.ladder import (
    Attempt,
    ClimbOutcome,
    Guards,
    Ladder,
    RunBudget,
    climb,
    cost_row,
)
from episignal_backend.ai.prompts import triage_prompt, triage_repair_prompt
from episignal_backend.ai.protocol import AiRepository, ChatModel
from episignal_backend.ai.schema import TriageVerdict, triage_json_schema
from episignal_backend.ai.validate import Rejected, RejectionReason
from episignal_backend.db.types import AiPurpose

DEFAULT_LIMIT = 200
DEFAULT_MAX_TIER = 3
TRIAGE_SNIPPET_CHARACTERS = 1200

logger = logging.getLogger("episignal_backend.ai.triage")


@dataclass(frozen=True)
class TriageResult:
    examined: int = 0
    triaged: int = 0
    repaired: int = 0
    filtered: int = 0
    failed: int = 0
    unavailable: int = 0
    requests: int = 0
    stopped_early: bool = False


def _validate(content: str) -> TriageVerdict:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as error:
        raise Rejected(RejectionReason.NOT_JSON, str(error)) from error
    try:
        return TriageVerdict.model_validate(payload)
    except ValidationError as error:
        raise Rejected(RejectionReason.SHAPE, str(error)) from error


def _request_builder(system: str, user: str) -> Callable[[ModelSpec], ChatRequest]:
    schema = triage_json_schema()

    def _request(spec: ModelSpec) -> ChatRequest:
        return ChatRequest(
            model_id=spec.model_id,
            system=system,
            user=user,
            response_schema=schema,
            schema_name="triage_verdict",
            temperature=0.0,
        )

    return _request


def _climb_once(
    *,
    signal: TriageableSignal,
    ladder: Ladder,
    budget: RunBudget,
    model: ChatModel,
    repair_error: str | None = None,
) -> tuple[ClimbOutcome, TriageVerdict | None, str | None, list[Attempt]]:
    if repair_error is None:
        system, user = triage_prompt(signal, max_characters=TRIAGE_SNIPPET_CHARACTERS)
    else:
        system, user = triage_repair_prompt(
            signal,
            error=repair_error,
            max_characters=TRIAGE_SNIPPET_CHARACTERS,
        )

    validation_error: str | None = None

    def accept(content: str) -> TriageVerdict:
        nonlocal validation_error
        try:
            return _validate(content)
        except Rejected as error:
            validation_error = str(error)
            raise

    attempts: list[Attempt] = []
    result = climb(
        ladder=ladder,
        budget=budget,
        model=model,
        request_for=_request_builder(system, user),
        accept=accept,
        on_attempt=attempts.append,
    )
    return result.outcome, result.value, validation_error or result.reason, attempts


def run_triage(
    repository: AiRepository,
    model: ChatModel,
    *,
    guards: Guards,
    limit: int = DEFAULT_LIMIT,
    max_tier: int = DEFAULT_MAX_TIER,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> TriageResult:
    ladder = Ladder.build(
        repository.models(),
        max_tier=max_tier,
        purpose=AiPurpose.TRIAGE,
    )
    budget = RunBudget(guards)
    pending = repository.awaiting_triage(limit=limit)

    triaged = 0
    repaired = 0
    filtered = 0
    failed = 0
    unavailable = 0
    requests = 0
    stopped_early = False

    for signal in pending:
        outcome, verdict, error, attempts = _climb_once(
            signal=signal,
            ladder=ladder,
            budget=budget,
            model=model,
        )
        all_attempts = list(attempts)
        repair_attempted = False
        repaired_this_signal = False

        if outcome is ClimbOutcome.REJECTED and not budget.exhausted:
            repair_attempted = True
            outcome, verdict, error, repair_attempts = _climb_once(
                signal=signal,
                ladder=ladder,
                budget=budget,
                model=model,
                repair_error=error or "answer did not match the triage schema",
            )
            all_attempts.extend(repair_attempts)
            repaired_this_signal = outcome is ClimbOutcome.ACCEPTED

        requests += len(all_attempts)
        at = now()

        try:
            for attempt in all_attempts:
                repository.record_request(
                    cost_row(
                        attempt,
                        purpose=AiPurpose.TRIAGE,
                        signal_id=signal.id,
                        batch_size=1,
                        at=at,
                    )
                )

            if outcome is ClimbOutcome.ACCEPTED and verdict is not None:
                disease_id = (
                    repository.resolve_disease(verdict.disease)
                    if verdict.disease is not None
                    else None
                )
                repository.record_triage(signal.id, verdict, disease_id, at)
                repository.commit()
                triaged += 1
                repaired += int(repaired_this_signal)
                filtered += int(not verdict.relevant)
            elif outcome is ClimbOutcome.REJECTED and repair_attempted:
                repository.record_triage_failure(signal.id)
                repository.commit()
                failed += 1
                logger.warning("Triage failed after one repair for signal %s: %s", signal.id, error)
            else:
                repository.commit()
                unavailable += int(outcome is ClimbOutcome.UNAVAILABLE)
        except Exception as storage_error:
            repository.rollback()
            logger.error(
                "Could not store triage for signal %s (%s)", signal.id, type(storage_error).__name__
            )

        if budget.exhausted or outcome is ClimbOutcome.GUARD:
            stopped_early = True
            break

    return TriageResult(
        examined=len(pending),
        triaged=triaged,
        repaired=repaired,
        filtered=filtered,
        failed=failed,
        unavailable=unavailable,
        requests=requests,
        stopped_early=stopped_early,
    )
