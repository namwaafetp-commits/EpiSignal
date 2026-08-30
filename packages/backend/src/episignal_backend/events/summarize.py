"""Event summarization: when and how an event's narrative is regenerated.

Runs only when a material change since the last summary warrants it. The
summary pass reads the event — disease, place, latest observation, and up to
``max_sources`` representative sources — and writes a versioned headline,
summary, status, and latest development onto the event. The versioned history
lives in ``event_summaries``; ``events.headline``/``summary`` denormalize the
newest accepted version for the public surface.

The pass is pure: ``run_summary`` imports neither SQLAlchemy nor httpx.
``configure_summary`` is the one wiring function, and it is the only import of
the routing layer here.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from episignal_backend.ai.documents import ChatRequest, ModelSpec, TokenUsage
from episignal_backend.ai.ladder import Attempt, cost_usd
from episignal_backend.ai.protocol import ChatModel, ModelUnavailable
from episignal_backend.ai.validate import Rejected, RejectionReason
from episignal_backend.config import Settings
from episignal_backend.db.types import AiOutcome, AiPurpose, EventStatus
from episignal_backend.events.documents import EventForSummary, SummarySource

SUMMARY_SCHEMA_NAME = "event_summary"
SUMMARY_TEMPERATURE = 0.0

SUMMARY_SYSTEM = (
    "You write one epidemiological event summary from the sources and figures you are given.\n"
    "Rules:\n"
    "- Summarize the EVENT, not one article. The latest observation is the most\n"
    "  recent reported state.\n"
    "- Every number you state must come from the sources or figures given.\n"
    "  Never invent a count, date, or place.\n"
    '- Distinguish reported facts from inference: say "officials reported" rather\n'
    '  than "it is confirmed".\n'
    "- If sources disagree, say so. Never silently pick one number as the truth.\n"
    "- status is one of: monitoring, ongoing, expanding, stable, declining,\n"
    "  resolved, unknown.\n"
    "- uncertainties lists what remains genuinely unknown or conflicting.\n"
    "- headline is a short, specific, information-dense line. summary is a few\n"
    "  sentences.\n"
    "- latest_development names the newest reported change, or says there is none.\n\n"
    "The object must match this JSON Schema exactly:\n"
)


class EventSummaryVerdict(BaseModel):
    """The summarizer's answer, validated strictly."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    headline: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    status: EventStatus
    latest_development: str = Field(min_length=1)
    uncertainties: list[str] = Field(default_factory=list)

    @field_validator("headline", "summary", "latest_development")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("summary text must say something")
        return collapsed


class SummaryOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SummaryResult:
    outcome: SummaryOutcome
    verdict: EventSummaryVerdict | None = None
    attempt: Attempt | None = None


def unique_summary_candidates(
    candidates: Sequence[EventForSummary],
) -> tuple[EventForSummary, ...]:
    """Keep one candidate per event for a single summarization run."""
    seen_event_ids: set[UUID] = set()
    unique: list[EventForSummary] = []
    for candidate in candidates:
        if candidate.event_id in seen_event_ids:
            continue
        seen_event_ids.add(candidate.event_id)
        unique.append(candidate)
    return tuple(unique)


def _accept(content: str) -> EventSummaryVerdict:
    try:
        payload = json.loads(content)
    except ValueError as error:
        raise Rejected(RejectionReason.NOT_JSON) from error
    try:
        return EventSummaryVerdict.model_validate(payload)
    except ValidationError as error:
        raise Rejected(RejectionReason.SHAPE) from error


@dataclass(frozen=True)
class SummaryWiring:
    """Everything the summarizer needs, resolved once.

    `model` is None when no provider key is configured: the summarizer then
    never runs, and the event simply keeps its previous headline and summary.
    """

    model: ChatModel | None
    spec: ModelSpec | None


def run_summary(
    model: ChatModel,
    spec: ModelSpec,
    *,
    event: EventForSummary,
    sources: tuple[SummarySource, ...],
) -> SummaryResult:
    """One request, one answer, one cost row's worth of evidence.

    The caller owns writing the cost row; this function only reports what a
    row would need, so the ledger rules stay in one place.
    """
    request = ChatRequest(
        model_id=spec.model_id,
        system=SUMMARY_SYSTEM + json.dumps(EventSummaryVerdict.model_json_schema(), sort_keys=True),
        user=json.dumps(
            {
                "event": {
                    "public_id": event.public_id,
                    "disease": event.disease,
                    "location": event.location,
                    "previous_headline": event.headline,
                    "previous_summary": event.summary,
                },
                "latest_observation": event.latest_observation,
                "sources": [
                    {
                        "title": source.title,
                        "source_name": source.source_name,
                        "is_official": source.is_official,
                        "published_at": source.published_at.isoformat()
                        if source.published_at is not None
                        else None,
                        "brief": [point.model_dump(mode="json") for point in source.brief],
                    }
                    for source in sources
                ],
            },
            ensure_ascii=False,
        ),
        response_schema=EventSummaryVerdict.model_json_schema(),
        schema_name=SUMMARY_SCHEMA_NAME,
        temperature=SUMMARY_TEMPERATURE,
    )

    try:
        response = model.complete(request)
    except ModelUnavailable:
        return SummaryResult(
            outcome=SummaryOutcome.UNAVAILABLE,
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
        verdict = _accept(response.content)
    except Rejected as rejection:
        return SummaryResult(
            outcome=SummaryOutcome.REJECTED,
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

    return SummaryResult(
        outcome=SummaryOutcome.ACCEPTED,
        verdict=verdict,
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


def configure_summary(settings: Settings, specs: list[ModelSpec]) -> SummaryWiring:
    """Resolve the summarizer model: the DeepSeek ``event_summary`` rung."""
    from episignal_backend.ai.routing import NoProviderKey, routed_from_settings

    try:
        model = routed_from_settings(settings, specs)
    except NoProviderKey:
        return SummaryWiring(model=None, spec=None)
    spec = next(
        (candidate for candidate in specs if candidate.purpose is AiPurpose.EVENT_SUMMARY),
        None,
    )
    return SummaryWiring(model=model, spec=spec)


def pick_representative_sources(
    sources: tuple[SummarySource, ...], *, max_sources: int
) -> tuple[SummarySource, ...]:
    """Order sources for the summary, then take the best ``max_sources``.

    Official sources first, then recency, then sources that carry a brief.
    The order is stable: a deterministic sort, never model judgement.
    """

    def publication_timestamp(source: SummarySource) -> datetime:
        return source.published_at or datetime.min.replace(tzinfo=UTC)

    ordered = sorted(
        sources,
        key=lambda source: (
            0 if source.is_official else 1,
            datetime.max.replace(tzinfo=UTC) - publication_timestamp(source),
            -len(source.brief),
            source.title,
        ),
    )
    selected = list(ordered[:max_sources])
    useful = [source for source in sources if source.brief]
    if selected and useful:
        newest_useful = max(useful, key=publication_timestamp)
        if newest_useful not in selected:
            selected[-1] = newest_useful
            order = {id(source): index for index, source in enumerate(ordered)}
            selected.sort(key=lambda source: order[id(source)])
    return tuple(selected)


def _counts_equals(left: dict[str, object] | None, right: dict[str, object] | None) -> bool:
    if left is None or right is None:
        return left is right
    keys = ("data_as_of", "confirmed_cases", "total_cases", "deaths", "new_cases", "new_deaths")
    return all(left.get(key) == right.get(key) for key in keys)


def should_resummarize(
    *,
    last_summarized_at: datetime | None,
    latest_observation: dict[str, object] | None,
    previous_counts: dict[str, object] | None,
    unsummarized_articles: int,
    now: datetime | None = None,
    max_age_hours: int = 24,
    new_article_count: int = 3,
) -> bool:
    """Decide whether an event needs a new summary.

    A summary is due when: it has never been written, the latest reported
    counts differ from the counts the previous summary was written against,
    enough new articles arrived since the last summary, or the summary is
    simply too old to trust. Anything else is not a material change, and the
    event keeps its current narrative.
    """
    reference = now or datetime.now(UTC)

    if last_summarized_at is None:
        return True
    if not _counts_equals(latest_observation, previous_counts):
        return True
    if unsummarized_articles >= new_article_count:
        return True
    return reference - last_summarized_at > timedelta(hours=max_age_hours)
