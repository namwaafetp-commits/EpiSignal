"""The epidemiological extraction pass.

Extracts structured epidemiological facts from relevant news articles. Every
extracted number and transmission flag is grounded in the source text. The
network climbs run concurrently; every read or write that touches the
repository stays on the calling thread, in selection order.

This module imports neither SQLAlchemy nor httpx.
"""

import logging
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from episignal_backend.ai.classify_disease import classify_disease
from episignal_backend.ai.documents import (
    ChatRequest,
    ExtractableCluster,
    ExtractableSignal,
    ModelSpec,
    StoredExtraction,
    TokenUsage,
)
from episignal_backend.ai.ladder import (
    Attempt,
    ClimbOutcome,
    ClimbResult,
    Guards,
    Ladder,
    RunBudget,
    climb,
    cost_row,
)
from episignal_backend.ai.prompts import (
    CLUSTER_MEMBER_CHARACTERS,
    cluster_extraction_prompt,
    extraction_prompt,
)
from episignal_backend.ai.protocol import AiRepository, ChatModel
from episignal_backend.ai.schema import Extraction, extraction_json_schema
from episignal_backend.ai.validate import validate_extraction
from episignal_backend.db.types import AiOutcome, AiPurpose, ReviewReason

DEFAULT_LIMIT = 100
DEFAULT_MAX_TIER = 3
DEFAULT_MAX_INPUT_CHARACTERS = 12000
DEFAULT_MIN_CONFIDENCE = 0.5
# Sequential by default so a pass stays deterministic unless the caller asks
# for concurrency; production wires EPISIGNAL_AI_EXTRACTION_WORKERS here.
DEFAULT_WORKERS = 1
# The floor under the extraction ladder. Live climbs recorded T1 Gemini
# accepting 0 of 7 extraction attempts (6 shape rejections, 1 ungrounded)
# while T2 and T3 carried the accepted answers, so starting below T2 spends
# tokens on a rung that, on this evidence, never answers first.
EXTRACTION_MIN_TIER = 2
EXTRACTION_TEMPERATURE = 0.0
EXTRACTION_SCHEMA_NAME = "extraction_response"
# Why a second pass that answered holds no disease: the model said null, or a
# slug outside the candidate set, and the ledger should say which.
NO_CANDIDATE_MATCHED = "no candidate matched"

logger = logging.getLogger("episignal_backend.ai.extract")


@dataclass(frozen=True)
class ExtractionResult:
    examined: int = 0
    extracted: int = 0
    reviewed: int = 0
    unavailable: int = 0
    storage_failed: int = 0
    requests: int = 0
    stopped_early: bool = False


def _request_builder(system: str, user: str) -> Callable[[ModelSpec], ChatRequest]:
    schema = extraction_json_schema()

    def _request(spec: ModelSpec) -> ChatRequest:
        return ChatRequest(
            model_id=spec.model_id,
            system=system,
            user=user,
            response_schema=schema,
            schema_name=EXTRACTION_SCHEMA_NAME,
            temperature=EXTRACTION_TEMPERATURE,
        )

    return _request


def _accept_builder(bodies: Sequence[str], min_confidence: float) -> Callable[[str], Extraction]:
    def _accept(content: str) -> Extraction:
        return validate_extraction(content, bodies, min_confidence=min_confidence)

    return _accept


def _top_rung(ladder: Ladder) -> ModelSpec:
    """The smartest rung. Rungs are sorted lowest tier first and the ladder is
    never empty, so the top of the ladder is its last rung."""
    return ladder.rungs[-1]


def _escalate_disease(
    repository: AiRepository,
    model: ChatModel,
    ladder: Ladder,
    *,
    signal_id: UUID,
    name: str,
    at: datetime,
) -> UUID | None:
    """The second pass for a name the vocabulary's exact match missed.

    The smartest rung chooses from the reviewed candidates, where null is an
    expected answer. The cost row is written even for a miss -- a request is a
    fact -- but its usage is left unknown rather than invented, because the
    classifier's contract hides it. Nothing here may raise: an unresolved
    disease is a review reason, and the escalation must never cost the
    extraction that earned it.
    """
    try:
        spec = _top_rung(ladder)
        candidates = repository.disease_candidates()
        if not candidates:
            # An empty vocabulary can only produce an invention; do not ask.
            return None
        slug = classify_disease(model, spec, name, candidates)
        repository.record_request(
            cost_row(
                Attempt(
                    spec=spec,
                    usage=TokenUsage(),
                    http_status=None,
                    latency_ms=0,
                    outcome=AiOutcome.ACCEPTED if slug else AiOutcome.REJECTED,
                    reason=None if slug else NO_CANDIDATE_MATCHED,
                    cost=Decimal("0"),
                ),
                purpose=AiPurpose.CLASSIFICATION,
                signal_id=signal_id,
                batch_size=1,
                at=at,
            )
        )
        if slug is None:
            return None
        return repository.resolve_disease_slug(slug)
    except Exception as error:
        logger.warning(
            "Disease classification for signal %s failed (%s)",
            signal_id,
            type(error).__name__,
        )
        return None


def _chunks(
    pending: Sequence[ExtractableSignal], size: int
) -> Iterator[Sequence[ExtractableSignal]]:
    for start in range(0, len(pending), size):
        yield pending[start : start + size]


def _run_pass(
    repository: AiRepository,
    model: ChatModel,
    pending: Sequence[ExtractableSignal],
    *,
    guards: Guards,
    demote_on_rejection: bool,
    max_tier: int = DEFAULT_MAX_TIER,
    min_tier: int = EXTRACTION_MIN_TIER,
    max_input_characters: int = DEFAULT_MAX_INPUT_CHARACTERS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    workers: int = DEFAULT_WORKERS,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ExtractionResult:
    ladder = Ladder.build(repository.models(), max_tier=max_tier, min_tier=min_tier)
    budget = RunBudget(guards)

    def climb_one(signal: ExtractableSignal) -> tuple[list[Attempt], ClimbResult[Extraction]]:
        """The network work for one signal. Touches no repository, so it is
        safe to run on a worker thread; the budget lock keeps the guard's
        arithmetic honest across concurrent climbs."""
        system, user = extraction_prompt(signal, max_characters=max_input_characters)
        attempts: list[Attempt] = []
        result = climb(
            ladder=ladder,
            budget=budget,
            model=model,
            request_for=_request_builder(system, user),
            accept=_accept_builder((signal.raw_text,), min_confidence),
            on_attempt=attempts.append,
        )
        return attempts, result

    extracted = 0
    reviewed = 0
    unavailable = 0
    storage_failed = 0
    requests = 0
    stopped_early = False

    # Chunks bound the work in flight and let the writes stream: finished
    # signals land in the database while later chunks are still climbing.
    # Submission order is preserved end to end, so the writes a run makes do
    # not depend on how many workers happened to be used.
    chunk_size = max(workers, 1) * 2
    for chunk in _chunks(pending, chunk_size):
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
            outcomes = list(pool.map(climb_one, chunk))
        for signal, (attempts, result) in zip(chunk, outcomes, strict=True):
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
                    disease_id = None
                    if result.value.disease is not None:
                        disease_id = repository.resolve_disease(result.value.disease.name)
                        if disease_id is None:
                            # The exact match missed. One request to the smartest
                            # rung may still resolve it; failing that, the signal
                            # keeps the DISEASE_UNRESOLVED review path unchanged.
                            disease_id = _escalate_disease(
                                repository,
                                model,
                                ladder,
                                signal_id=signal.id,
                                name=result.value.disease.name,
                                at=at,
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
                elif result.outcome is ClimbOutcome.REJECTED and demote_on_rejection:
                    repository.open_review(signal.id, reason=ReviewReason.EXTRACTION_REJECTED)

                repository.commit()
            except Exception as error:
                repository.rollback()
                storage_failed += 1
                logger.error(
                    "Could not store extraction for signal %s (%s)",
                    signal.id,
                    type(error).__name__,
                )
            else:
                if result.outcome is ClimbOutcome.ACCEPTED and result.value is not None:
                    extracted += 1
                elif result.outcome is ClimbOutcome.REJECTED:
                    reviewed += 1
                else:
                    unavailable += 1

            if result.outcome is ClimbOutcome.GUARD:
                stopped_early = True
        if stopped_early:
            break

    return ExtractionResult(
        examined=len(pending),
        extracted=extracted,
        reviewed=reviewed,
        unavailable=unavailable,
        storage_failed=storage_failed,
        requests=requests,
        stopped_early=stopped_early,
    )


def _run_cluster_pass(
    repository: AiRepository,
    model: ChatModel,
    groups: Sequence[ExtractableCluster],
    *,
    guards: Guards,
    max_tier: int = DEFAULT_MAX_TIER,
    min_tier: int = EXTRACTION_MIN_TIER,
    max_input_characters: int = CLUSTER_MEMBER_CHARACTERS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[ExtractionResult, list[ExtractableSignal]]:
    ladder = Ladder.build(repository.models(), max_tier=max_tier, min_tier=min_tier)
    budget = RunBudget(guards)
    top_spec = _top_rung(ladder)

    extracted = 0
    reviewed = 0
    unavailable = 0
    storage_failed = 0
    requests = 0
    stopped_early = False
    fallbacks: list[ExtractableSignal] = []

    single_rung_ladder = Ladder(rungs=(top_spec,))

    for group in groups:
        if budget.exhausted:
            stopped_early = True
            break

        system, user = cluster_extraction_prompt(group.members, max_characters=max_input_characters)
        attempts: list[Attempt] = []

        result = climb(
            ladder=single_rung_ladder,
            budget=budget,
            model=model,
            request_for=_request_builder(system, user),
            accept=_accept_builder(group.bodies, min_confidence),
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
                        signal_id=group.representative_id,
                        batch_size=len(group.members),
                        at=at,
                    )
                )

            if result.outcome is ClimbOutcome.ACCEPTED and result.value is not None:
                disease_id = None
                if result.value.disease is not None:
                    disease_id = repository.resolve_disease(result.value.disease.name)
                    if disease_id is None:
                        disease_id = _escalate_disease(
                            repository,
                            model,
                            ladder,
                            signal_id=group.representative_id,
                            name=result.value.disease.name,
                            at=at,
                        )
                member_ids = [m.id for m in group.members]
                repository.record_cluster_extraction(
                    representative_id=group.representative_id,
                    member_ids=member_ids,
                    stored=StoredExtraction(
                        extraction=result.value,
                        disease_id=disease_id,
                        model_id=attempts[-1].spec.model_id,
                        processed_at=at,
                    ),
                )
                repository.commit()
                extracted += 1
            else:
                repository.commit()
                rep_member = group.members[0]
                fallback_signal = ExtractableSignal(
                    id=rep_member.id,
                    title=rep_member.title,
                    raw_text=rep_member.raw_text,
                )
                fallbacks.append(fallback_signal)

                if result.outcome is ClimbOutcome.REJECTED:
                    reviewed += 1
                else:
                    unavailable += 1

        except Exception as error:
            repository.rollback()
            storage_failed += 1
            logger.error(
                "Could not store cluster extraction for group %s (%s)",
                group.group_id,
                type(error).__name__,
            )

        if result.outcome is ClimbOutcome.GUARD:
            stopped_early = True
            break

    return (
        ExtractionResult(
            examined=len(groups),
            extracted=extracted,
            reviewed=reviewed,
            unavailable=unavailable,
            storage_failed=storage_failed,
            requests=requests,
            stopped_early=stopped_early,
        ),
        fallbacks,
    )


def run_extraction(
    repository: AiRepository,
    model: ChatModel,
    *,
    guards: Guards,
    limit: int = DEFAULT_LIMIT,
    max_tier: int = DEFAULT_MAX_TIER,
    max_input_characters: int = DEFAULT_MAX_INPUT_CHARACTERS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    workers: int = DEFAULT_WORKERS,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ExtractionResult:
    """Extract from signals, starting with cluster groups and falling back to single signals."""
    # 1. Cluster Pass
    groups = repository.awaiting_cluster_extraction(limit=limit)
    cluster_result, fallbacks = _run_cluster_pass(
        repository,
        model,
        groups,
        guards=guards,
        max_tier=max_tier,
        min_confidence=min_confidence,
        now=now,
    )

    # 2. Single Pass (for Fallbacks and Ordinary Signals)
    single_limit = max(0, limit - cluster_result.extracted)
    fallback_ids = {sig.id for sig in fallbacks}
    ordinary = [
        sig
        for sig in repository.awaiting_extraction(limit=single_limit)
        if sig.id not in fallback_ids
    ]
    pending = list(fallbacks) + ordinary

    single_result = _run_pass(
        repository,
        model,
        pending[:single_limit],
        guards=guards,
        demote_on_rejection=True,
        max_tier=max_tier,
        max_input_characters=max_input_characters,
        min_confidence=min_confidence,
        workers=workers,
        now=now,
    )

    # Combine Results
    return ExtractionResult(
        examined=cluster_result.examined + single_result.examined,
        extracted=cluster_result.extracted + single_result.extracted,
        reviewed=cluster_result.reviewed + single_result.reviewed,
        unavailable=cluster_result.unavailable + single_result.unavailable,
        storage_failed=cluster_result.storage_failed + single_result.storage_failed,
        requests=cluster_result.requests + single_result.requests,
        stopped_early=cluster_result.stopped_early or single_result.stopped_early,
    )


def run_backfill(
    repository: AiRepository,
    model: ChatModel,
    *,
    guards: Guards,
    limit: int = DEFAULT_LIMIT,
    max_tier: int = DEFAULT_MAX_TIER,
    max_input_characters: int = DEFAULT_MAX_INPUT_CHARACTERS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    workers: int = DEFAULT_WORKERS,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ExtractionResult:
    """Re-extract signals whose stored extraction predates the current schema.

    Identical to the extraction pass in every respect but its selection, which
    is why it shares that pass rather than copying it. A rejected answer leaves
    the existing extraction untouched: a backfill never destroys a good old
    answer in order to store a bad new one.
    """
    return _run_pass(
        repository,
        model,
        repository.awaiting_backfill(limit=limit),
        guards=guards,
        demote_on_rejection=False,
        max_tier=max_tier,
        max_input_characters=max_input_characters,
        min_confidence=min_confidence,
        workers=workers,
        now=now,
    )
