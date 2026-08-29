"""The delta pass: what changed between two briefs of one event.

Runs after a cluster attaches to an event that was already observed inside the
follow-up window. Its input is the latest attached brief and the newly attached
brief — roughly three hundred tokens, no article re-read — and its output is an
updated five-slot brief plus an explicit what-changed note, written onto the
newest observation row. The pass is enrichment: it never gates the attach, and
a pass that cannot run leaves the attach exactly as it was.

This module imports neither SQLAlchemy nor httpx.
"""

import json
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from episignal_backend.ai.documents import ChatRequest, ModelSpec, TokenUsage
from episignal_backend.ai.ladder import Attempt, cost_usd
from episignal_backend.ai.protocol import ChatModel, ModelUnavailable
from episignal_backend.ai.schema import BRIEF_SLOTS, BriefPoint
from episignal_backend.ai.validate import Rejected, RejectionReason
from episignal_backend.db.types import AiOutcome

DELTA_SCHEMA_NAME = "event_delta"
DELTA_TEMPERATURE = 0.0

DELTA_SYSTEM = """You compare two five-slot epidemiological briefs of one ongoing event.
The previous brief is what the event was last known to be. The new brief is a later report.
Produce the updated brief a reader should now see, then state plainly what changed.
Rules:
- Every slot is filled, in order: what_where, counts, timing, spread, reporting.
- Prefer the new report's numbers when they supersede older ones; keep an older
  figure only when the new report does not address it, and say it is the earlier figure.
- Never invent a number, a place, or a date neither brief carries.
- What changed must name only real differences between the two briefs."""


class DeltaBrief(BaseModel):
    """The delta pass output: an updated brief plus what changed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    brief: tuple[BriefPoint, ...]
    what_changed: str = Field(min_length=1)

    @field_validator("brief")
    @classmethod
    def brief_fills_every_slot_in_order(
        cls, value: tuple[BriefPoint, ...]
    ) -> tuple[BriefPoint, ...]:
        # The same rule the extraction brief carries: an updated brief that
        # dropped slots or reordered them is not the same shape readers were
        # promised, and quietly repairing it would teach the next reader the
        # order was never load-bearing.
        if tuple(point.slot for point in value) != BRIEF_SLOTS:
            raise ValueError("brief must carry exactly one point per slot, in slot order")
        return value

    @field_validator("what_changed")
    @classmethod
    def what_changed_is_not_blank(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("what_changed must say something")
        return collapsed


class DeltaOutcome(StrEnum):
    ACCEPTED = "accepted"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DeltaResult:
    outcome: DeltaOutcome
    delta: DeltaBrief | None = None
    attempt: Attempt | None = None


def _brief_json(points: tuple[BriefPoint, ...]) -> str:
    return json.dumps(
        [
            {"slot": point.slot.value, "text": point.text, "reported": point.reported}
            for point in points
        ],
        ensure_ascii=False,
    )


def _accept(content: str) -> DeltaBrief:
    try:
        payload = json.loads(content)
    except ValueError as error:
        raise Rejected(RejectionReason.NOT_JSON) from error
    try:
        return DeltaBrief.model_validate(payload)
    except ValidationError as error:
        raise Rejected(RejectionReason.SHAPE) from error


def run_delta(
    model: ChatModel,
    spec: ModelSpec,
    *,
    previous: tuple[BriefPoint, ...],
    new: tuple[BriefPoint, ...],
) -> DeltaResult:
    """One request, one answer, one cost row's worth of facts.

    The caller owns writing the cost row; this function only reports what a
    row would need, so the ledger rules stay in one place.
    """
    request = ChatRequest(
        model_id=spec.model_id,
        system=DELTA_SYSTEM,
        user=json.dumps(
            {"previous": json.loads(_brief_json(previous)), "new": json.loads(_brief_json(new))},
            ensure_ascii=False,
        ),
        response_schema=DeltaBrief.model_json_schema(),
        schema_name=DELTA_SCHEMA_NAME,
        temperature=DELTA_TEMPERATURE,
    )

    try:
        response = model.complete(request)
    except ModelUnavailable:
        return DeltaResult(
            outcome=DeltaOutcome.UNAVAILABLE,
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
        delta = _accept(response.content)
    except Rejected as rejection:
        return DeltaResult(
            outcome=DeltaOutcome.UNAVAILABLE,
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

    return DeltaResult(
        outcome=DeltaOutcome.ACCEPTED,
        delta=delta,
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


def delta_payload(delta: DeltaBrief) -> dict[str, object]:
    """The JSONB written onto the observation row."""
    return {
        "what_changed": delta.what_changed,
        "brief": [point.model_dump(mode="json") for point in delta.brief],
    }
