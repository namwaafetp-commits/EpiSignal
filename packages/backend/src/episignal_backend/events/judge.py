"""The ambiguous-match judge: is a candidate event the same event or not?

Runs only when the deterministic score fell between the review threshold and
the auto threshold. The judge reads the new report's title and snippet against
the candidate event's headline and its recent source titles, and answers
``same_event``. A false merge is worse than a duplicate event, so the assembly
prefers a new event whenever the judge is uncertain or unavailable.

The pass is pure: ``run_judge`` imports neither SQLAlchemy nor httpx.
``configure_judge`` is the one wiring function, and it is the only import of
the routing layer here.
"""

import json
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from episignal_backend.ai.documents import ChatRequest, ModelSpec, TokenUsage
from episignal_backend.ai.ladder import Attempt, cost_usd
from episignal_backend.ai.protocol import ChatModel, ModelUnavailable
from episignal_backend.ai.validate import Rejected, RejectionReason
from episignal_backend.config import Settings
from episignal_backend.db.types import AiOutcome, AiPurpose

JUDGE_SCHEMA_NAME = "event_match_judge"
JUDGE_TEMPERATURE = 0.0

JUDGE_SYSTEM = (
    "You decide whether a new report is about the SAME outbreak event or a different one.\n"
    "Compare the new report with the candidate event's headline and its recent report titles.\n"
    "Rules:\n"
    "- Same event means the same disease in the same place during the same ongoing episode.\n"
    "- A follow-up with updated case counts is the same event. A different place, or a clearly\n"
    "  different episode of the same disease, is a different event.\n"
    "- Do not override a hard geography contradiction: a different country, or a different\n"
    "  clearly-named province, means a different event no matter how similar the wording.\n"
    "- When genuinely uncertain, answer same_event false: a false merge is worse\n"
    "  than a duplicate event.\n"
    "- reason must name the specific evidence that decided the answer."
)


class EventMatchJudgement(BaseModel):
    """The judge's answer, validated strictly."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    same_event: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def reason_is_not_blank(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("reason must say something")
        return collapsed


class JudgeOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class JudgeResult:
    outcome: JudgeOutcome
    judgement: EventMatchJudgement | None = None
    attempt: Attempt | None = None


def _accept(content: str) -> EventMatchJudgement:
    try:
        payload = json.loads(content)
    except ValueError as error:
        raise Rejected(RejectionReason.NOT_JSON) from error
    try:
        return EventMatchJudgement.model_validate(payload)
    except ValidationError as error:
        raise Rejected(RejectionReason.SHAPE) from error


def run_judge(
    model: ChatModel,
    spec: ModelSpec,
    *,
    new_title: str,
    new_snippet: str,
    event_title: str,
    event_context: str,
    recent_source_titles: tuple[str, ...],
) -> JudgeResult:
    """One request, one answer, one cost row's worth of evidence.

    The caller owns writing the cost row; this function only reports what a
    row would need, so the ledger rules stay in one place.
    """
    request = ChatRequest(
        model_id=spec.model_id,
        system=JUDGE_SYSTEM,
        user=json.dumps(
            {
                "new_report": {"title": new_title, "snippet": new_snippet},
                "candidate_event": {
                    "headline": event_title,
                    "context": event_context,
                    "recent_source_titles": list(recent_source_titles),
                },
            },
            ensure_ascii=False,
        ),
        response_schema=EventMatchJudgement.model_json_schema(),
        schema_name=JUDGE_SCHEMA_NAME,
        temperature=JUDGE_TEMPERATURE,
    )

    try:
        response = model.complete(request)
    except ModelUnavailable:
        return JudgeResult(
            outcome=JudgeOutcome.UNAVAILABLE,
            attempt=Attempt(
                spec=spec,
                usage=TokenUsage(),
                http_status=None,
                latency_ms=0,
                outcome=AiOutcome.UNAVAILABLE,
                reason=None,
                cost=cost_usd(TokenUsage(), spec),
            ),
        )

    try:
        judgement = _accept(response.content)
    except Rejected as rejection:
        return JudgeResult(
            outcome=JudgeOutcome.REJECTED,
            attempt=Attempt(
                spec=spec,
                usage=response.usage,
                http_status=response.http_status,
                latency_ms=response.latency_ms,
                outcome=AiOutcome.REJECTED,
                reason=rejection.reason.value,
                cost=cost_usd(response.usage, spec),
            ),
        )

    return JudgeResult(
        outcome=JudgeOutcome.ACCEPTED,
        judgement=judgement,
        attempt=Attempt(
            spec=spec,
            usage=response.usage,
            http_status=response.http_status,
            latency_ms=response.latency_ms,
            outcome=AiOutcome.ACCEPTED,
            reason=None,
            cost=cost_usd(response.usage, spec),
        ),
    )


@dataclass(frozen=True)
class JudgeWiring:
    """Everything the assembly needs to judge an ambiguous match, resolved once.

    `model` is None when no provider key is configured: the assembly then
    prefers a new event for every ambiguous match, which is the conservative
    answer, so the pass degrades safely.
    """

    model: ChatModel | None
    spec: ModelSpec | None


def configure_judge(settings: Settings, specs: list[ModelSpec]) -> JudgeWiring:
    """Resolve the judge model. The cheap classifier rung is preferred.

    The lean MVP selects Llama 3.1 8B (purpose ``triage``) for judgement calls.
    When the roster has no purpose-scoped rung, the lowest general tier is used.
    """
    from episignal_backend.ai.routing import NoProviderKey, routed_from_settings

    try:
        model = routed_from_settings(settings, specs)
    except NoProviderKey:
        return JudgeWiring(model=None, spec=None)

    spec = next(
        (candidate for candidate in specs if candidate.purpose is AiPurpose.TRIAGE),
        next((candidate for candidate in specs if candidate.tier == 1), None),
    )
    return JudgeWiring(model=model, spec=spec)
