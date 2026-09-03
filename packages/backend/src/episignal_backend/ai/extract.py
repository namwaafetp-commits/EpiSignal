"""Gemini identity extraction after relevance-gated retrieval."""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from episignal_backend.ai.documents import (
    ChatRequest,
    ExtractableSignal,
    ModelSpec,
    StoredExtraction,
)
from episignal_backend.ai.ladder import Attempt, ClimbOutcome, Guards, Ladder, RunBudget, cost_row
from episignal_backend.ai.prompts import extraction_prompt, identity_repair_prompt
from episignal_backend.ai.protocol import AiRepository, ChatModel
from episignal_backend.ai.registry import model_for_purpose
from episignal_backend.ai.schema import Extraction, extraction_json_schema
from episignal_backend.ai.validate import validate_extraction
from episignal_backend.db.types import AiPurpose

EXTRACTION_SCHEMA_NAME = "extraction_identity"
DEFAULT_MAX_INPUT_CHARACTERS = 12000
DEFAULT_MIN_CONFIDENCE = 0.0
DEFAULT_WORKERS = 1
EXTRACTION_MIN_TIER = 1
EXTRACTION_TEMPERATURE = 0.0
logger = logging.getLogger(__name__)


def build_extraction_ladder(repository: AiRepository, *, max_tier: int) -> Ladder:
    """Compatibility seam returning a one-rung Gemini ladder."""
    spec = model_for_purpose(repository.models(), AiPurpose.EXTRACTION)
    if spec.tier > max_tier:
        raise ValueError("configured extraction model exceeds max tier")
    return Ladder(rungs=(spec,))


@dataclass(frozen=True)
class ExtractionResult:
    examined: int = 0
    extracted: int = 0
    reviewed: int = 0
    unavailable: int = 0
    storage_failed: int = 0
    requests: int = 0
    expanded_retries: int = 0
    stopped_early: bool = False


@dataclass(frozen=True)
class ExtractionSignalResult:
    outcome: ClimbOutcome
    extraction: Extraction | None
    error: str | None
    attempts: tuple[Attempt, ...]
    expanded_retries: int = 0
    stopped_early: bool = False


def _has_event_identity(extraction: Extraction) -> bool:
    return extraction.disease is not None and any(
        location.country is not None for location in extraction.locations
    )


def _identity_rank(extraction: Extraction) -> tuple[int, int, int, int]:
    """Rank accepted partial identity deterministically for retry selection."""
    countries = sum(location.country is not None for location in extraction.locations)
    towns = sum(location.town is not None for location in extraction.locations)
    return (int(extraction.disease is not None), int(countries > 0), countries, towns)


def extract_signal(
    signal: ExtractableSignal,
    model: ChatModel,
    *,
    spec: ModelSpec | None = None,
    ladder: Ladder | None = None,
    budget: RunBudget,
    max_input_characters: int = 12000,
    min_confidence: float = 0.0,
) -> ExtractionSignalResult:
    """One Gemini request plus exactly one same-model identity repair."""
    del min_confidence
    if spec is None:
        if ladder is None or not ladder.rungs:
            raise ValueError("extraction requires a configured model")
        spec = ladder.rungs[-1]

    def ask(builder: Callable[..., tuple[str, str]]) -> ExtractionSignalResult:
        system, user = builder(signal, max_characters=max_input_characters)
        attempts: list[Attempt] = []
        from episignal_backend.ai.ladder import Ladder, climb

        result = climb(
            ladder=Ladder(rungs=(spec,)),
            budget=budget,
            model=model,
            request_for=lambda _: ChatRequest(
                model_id=spec.model_id,
                system=system,
                user=user,
                response_schema=extraction_json_schema(),
                schema_name=EXTRACTION_SCHEMA_NAME,
                temperature=0.0,
            ),
            accept=lambda content: validate_extraction(content),
            on_attempt=attempts.append,
        )
        return ExtractionSignalResult(
            outcome=result.outcome,
            extraction=result.value,
            error=result.reason,
            attempts=tuple(attempts),
            stopped_early=result.outcome is ClimbOutcome.GUARD,
        )

    initial = ask(extraction_prompt)
    if initial.outcome is not ClimbOutcome.ACCEPTED or initial.extraction is None:
        return initial
    if _has_event_identity(initial.extraction):
        return initial

    retry = ask(identity_repair_prompt)
    chosen = initial
    if retry.extraction is not None and _identity_rank(retry.extraction) > _identity_rank(
        initial.extraction
    ):
        chosen = retry
    return ExtractionSignalResult(
        outcome=chosen.outcome,
        extraction=chosen.extraction,
        error=chosen.error,
        attempts=initial.attempts + retry.attempts,
        expanded_retries=1,
        stopped_early=retry.stopped_early,
    )


def _run_pass(
    repository: AiRepository,
    model: ChatModel,
    pending: Sequence[ExtractableSignal],
    *,
    spec: ModelSpec,
    guards: Guards,
    demote_on_rejection: bool,
    max_input_characters: int = 12000,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ExtractionResult:
    budget = RunBudget(guards)
    extracted = reviewed = unavailable = storage_failed = requests = retries = 0
    for signal in pending:
        result = extract_signal(
            signal, model, spec=spec, budget=budget, max_input_characters=max_input_characters
        )
        requests += len(result.attempts)
        retries += result.expanded_retries
        at = now()
        try:
            for attempt in result.attempts:
                repository.record_request(
                    cost_row(
                        attempt,
                        purpose=AiPurpose.EXTRACTION,
                        signal_id=signal.id,
                        batch_size=1,
                        at=at,
                    )
                )
            if result.outcome is ClimbOutcome.ACCEPTED and result.extraction is not None:
                disease_id = (
                    repository.resolve_disease(result.extraction.disease)
                    if result.extraction.disease
                    else None
                )
                repository.record_extraction(
                    signal.id,
                    StoredExtraction(
                        extraction=result.extraction,
                        disease_id=disease_id,
                        model_id=spec.model_id,
                        processed_at=at,
                    ),
                )
            elif result.outcome is ClimbOutcome.REJECTED:
                if demote_on_rejection:
                    repository.record_extraction_failure(signal.id)
            else:
                pass
            repository.commit()
            if result.outcome is ClimbOutcome.ACCEPTED and result.extraction is not None:
                extracted += 1
            elif result.outcome is ClimbOutcome.REJECTED:
                reviewed += 1
            else:
                unavailable += 1
        except Exception:
            repository.rollback()
            storage_failed += 1
            logger.error("extraction storage failed for signal %s", signal.id, exc_info=True)
    return ExtractionResult(
        examined=len(pending),
        extracted=extracted,
        reviewed=reviewed,
        unavailable=unavailable,
        storage_failed=storage_failed,
        requests=requests,
        expanded_retries=retries,
        stopped_early=budget.exhausted,
    )


def run_extraction(
    repository: AiRepository,
    model: ChatModel,
    *,
    guards: Guards,
    limit: int = 100,
    max_tier: int = 3,
    max_input_characters: int = 12000,
    min_confidence: float = 0.0,
    workers: int = 1,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    signal_ids: Sequence[UUID] | None = None,
) -> ExtractionResult:
    del max_tier, min_confidence, workers
    spec = model_for_purpose(repository.models(), AiPurpose.EXTRACTION)
    return _run_pass(
        repository,
        model,
        repository.awaiting_extraction(limit=limit)
        if signal_ids is None
        else repository.awaiting_extraction(limit=limit, signal_ids=signal_ids),
        spec=spec,
        guards=guards,
        demote_on_rejection=True,
        max_input_characters=max_input_characters,
        now=now,
    )


def run_backfill(
    repository: AiRepository,
    model: ChatModel,
    *,
    guards: Guards,
    limit: int = 100,
    max_tier: int = 3,
    max_input_characters: int = 12000,
    min_confidence: float = 0.0,
    workers: int = 1,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ExtractionResult:
    del max_tier, min_confidence, workers
    spec = model_for_purpose(repository.models(), AiPurpose.EXTRACTION)
    return _run_pass(
        repository,
        model,
        repository.awaiting_backfill(limit=limit),
        spec=spec,
        guards=guards,
        demote_on_rejection=False,
        max_input_characters=max_input_characters,
        now=now,
    )
