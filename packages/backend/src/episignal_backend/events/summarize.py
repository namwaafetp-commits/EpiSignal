"""Event summarization: versioned, event-level EpiSignal flash briefs.

Runs only for a new event or a material change in its consolidated observations.
The model returns the structured brief; the renderer writes the exact public
flash-brief format. The versioned history lives in ``event_summaries`` and the
rendered text is denormalized onto ``events.summary``.

The pass is pure: ``run_summary`` imports neither SQLAlchemy nor httpx.
``configure_summary`` is the one wiring function, and it is the only import of
the routing layer here.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from episignal_backend.ai.documents import ChatRequest, ModelSpec, TokenUsage
from episignal_backend.ai.ladder import Attempt, cost_usd
from episignal_backend.ai.protocol import ChatModel, ModelUnavailable, NoModelsConfigured
from episignal_backend.ai.registry import model_for_purpose
from episignal_backend.ai.validate import Rejected, RejectionReason
from episignal_backend.config import Settings
from episignal_backend.db.types import AiOutcome, AiPurpose
from episignal_backend.diagnostics import (
    classify_ai_failure,
    http_status_class,
    sanitize_failure_message,
)
from episignal_backend.events.documents import EventForSummary, SummarySource

SUMMARY_SCHEMA_NAME = "event_summary"
SUMMARY_TEMPERATURE = 0.0

SUMMARY_SYSTEM = (
    "You write one EpiSignal epidemiological event flash brief from all linked "
    "clean article sources.\n"
    "Rules:\n"
    "- Summarize the EVENT, never an individual article. Use the supplied article "
    "title, publication time, source, and clean article text as the evidence.\n"
    "- The linked article sources are authoritative for narrative facts. Do not "
    "expect or invent deprecated extraction fields such as cases, deaths, CFR, "
    "pathogen, transmission, dates, or response actions.\n"
    "- Preserve confirmed, suspected, and probable distinctions.\n"
    "- Every number, disease, location, response, and risk claim must be supported "
    "by the supplied article evidence. Never invent or silently "
    "resolve conflicting evidence.\n"
    "- Use trajectory exactly as one of: Emerging, Increasing, Stable, Declining, "
    "Contained, Resolved, Unclear. Use Unclear when unsupported.\n"
    "- Use `Not yet established.` for an unsupported key driver, `No specific "
    "response reported.` when no response is evidenced, and `Insufficient evidence "
    "for a broader risk assessment.` when risk cannot be assessed.\n"
    "- The headline must follow: [Pathogen/Disease] Outbreak: [Location] — "
    "[Trajectory]. The application canonicalizes the disease, location, and "
    "trajectory from the grouped event.\n"
    "- The rendered brief uses these exact labels: The Snapshot:, Key Driver:, "
    "Response:, and Public/Global Risk:.\n"
    "- Choose 1 to 3 concise, evidence-grounded snapshot facts that are most\n"
    "  decision-relevant for this event. Cases, deaths, and CFR are optional;\n"
    "  never force a metric that is unsupported or less informative.\n"
    "- If linked sources disagree, state the disagreement explicitly.\n\n"
    "The object must match this JSON Schema exactly:\n"
)


class SummaryTrajectory(StrEnum):
    EMERGING = "Emerging"
    INCREASING = "Increasing"
    STABLE = "Stable"
    DECLINING = "Declining"
    CONTAINED = "Contained"
    RESOLVED = "Resolved"
    UNCLEAR = "Unclear"


SummarySnapshot = tuple[str, ...]


class EventSummaryVerdict(BaseModel):
    """The summarizer's answer, validated strictly."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    headline: str = Field(min_length=1)
    trajectory: SummaryTrajectory
    snapshot: SummarySnapshot = Field(min_length=1, max_length=3)
    key_driver: str = Field(min_length=1)
    response: str = Field(min_length=1)
    risk: str = Field(min_length=1)

    @field_validator("headline", "key_driver", "response", "risk")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("summary text must say something")
        return collapsed

    @field_validator("snapshot")
    @classmethod
    def snapshot_facts_are_not_blank(cls, value: SummarySnapshot) -> SummarySnapshot:
        facts = tuple(" ".join(fact.split()) for fact in value)
        if any(not fact for fact in facts):
            raise ValueError("snapshot facts must say something")
        return facts


class SummaryOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SummaryResult:
    outcome: SummaryOutcome
    verdict: EventSummaryVerdict | None = None
    attempt: Attempt | None = None
    failure_reason: str | None = None
    failure_exception_class: str | None = None
    retry_count: int = 0


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


def _accept(content: str, *, event: EventForSummary) -> EventSummaryVerdict:
    try:
        payload = json.loads(content)
    except ValueError as error:
        raise Rejected(RejectionReason.NOT_JSON) from error
    try:
        verdict = EventSummaryVerdict.model_validate(payload)
    except ValidationError as error:
        raise Rejected(RejectionReason.SHAPE) from error

    # Disease and location are already validated event metadata. Rebuild the
    # heading from those fields so a model cannot move an event to a place or
    # disease merely by writing a plausible headline.
    disease = event.disease.strip() or "Unspecified pathogen/disease"
    disease = disease[:1].upper() + disease[1:]
    location = event.location.strip() or "Unresolved location"
    return verdict.model_copy(
        update={
            "headline": f"{disease} Outbreak: {location} — {verdict.trajectory.value}",
        }
    )


def render_event_flash_brief(verdict: EventSummaryVerdict) -> str:
    """Render the only public event-summary narrative format."""
    return "\n\n".join(
        (
            verdict.headline,
            "The Snapshot:\n" + " | ".join(verdict.snapshot),
            f"Key Driver:\n{verdict.key_driver}",
            f"Response:\n{verdict.response}",
            f"Public/Global Risk:\n{verdict.risk}",
        )
    )


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
                "observations": list(event.observations),
                "sources": [
                    {
                        "title": source.title,
                        "source_name": source.source_name,
                        "is_official": source.is_official,
                        "published_at": source.published_at.isoformat()
                        if source.published_at is not None
                        else None,
                        "article_text": source.article_text,
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
    except ModelUnavailable as error:
        return SummaryResult(
            outcome=SummaryOutcome.UNAVAILABLE,
            attempt=Attempt(
                spec=spec,
                usage=TokenUsage(),
                http_status=getattr(error, "http_status", None),
                latency_ms=0,
                outcome=AiOutcome.UNAVAILABLE,
                reason=None,
                cost=cost_usd(TokenUsage(), spec),
            ),
            failure_reason=str(error) or None,
            failure_exception_class=type(error).__name__,
            retry_count=max(0, getattr(error, "attempts", 1) - 1),
        )

    try:
        verdict = _accept(response.content, event=event)
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
            failure_reason=rejection.reason.value,
            failure_exception_class=type(rejection).__name__,
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


def build_summary_failure_diagnostic(
    event: EventForSummary, result: SummaryResult, *, at: datetime
) -> dict[str, object] | None:
    """Build bounded case-level telemetry for a non-successful summary."""
    if result.outcome is SummaryOutcome.ACCEPTED or result.attempt is None:
        return None
    attempt = result.attempt
    return {
        "event_id": event.public_id,
        "timestamp": at.isoformat(),
        "provider": attempt.spec.provider.value,
        "model": attempt.spec.model_id,
        "category": classify_ai_failure(
            result.failure_reason,
            http_status=attempt.http_status,
            rejected=result.outcome is SummaryOutcome.REJECTED,
        ).value,
        "retry_count": result.retry_count,
        "provider_status_class": http_status_class(attempt.http_status),
        "exception_class": result.failure_exception_class,
        "message": sanitize_failure_message(result.failure_reason),
    }


def configure_summary(settings: Settings, specs: list[ModelSpec]) -> SummaryWiring:
    """Resolve Mistral Small 3.2 through the purpose registry."""
    from episignal_backend.ai.routing import NoProviderKey, routed_from_settings

    try:
        model = routed_from_settings(settings, specs)
    except NoProviderKey:
        return SummaryWiring(model=None, spec=None)
    try:
        spec = model_for_purpose(specs, AiPurpose.EVENT_SUMMARY)
    except NoModelsConfigured:
        return SummaryWiring(model=None, spec=None)
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
            -len(source.article_text),
            source.title,
        ),
    )
    selected = list(ordered[:max_sources])
    useful = [source for source in sources if source.article_text.strip()]
    if selected and useful:
        newest_useful = max(useful, key=publication_timestamp)
        if newest_useful not in selected:
            selected[-1] = newest_useful
            order = {id(source): index for index, source in enumerate(ordered)}
            selected.sort(key=lambda source: order[id(source)])
    return tuple(selected)


_MATERIAL_OBSERVATION_FIELDS = (
    "confirmed_cases",
    "probable_cases",
    "suspected_cases",
    "total_cases",
    "deaths",
    "new_cases",
    "new_deaths",
    "cfr",
    "affected_admin_areas",
    "geographic_extent",
    "material_facts",
)


def _counts_equals(left: dict[str, object] | None, right: dict[str, object] | None) -> bool:
    if left is None or right is None:
        return left is right

    def comparable(value: object) -> object:
        if isinstance(value, dict):
            return {
                key: comparable(item)
                for key, item in value.items()
                if key not in {"source_span", "source_index"}
            }
        if isinstance(value, list):
            return [comparable(item) for item in value]
        return value

    return all(
        comparable(left.get(key)) == comparable(right.get(key))
        for key in _MATERIAL_OBSERVATION_FIELDS
    )


def should_resummarize(
    *,
    last_summarized_at: datetime | None,
    latest_observation: dict[str, object] | None,
    previous_counts: dict[str, object] | None,
    unsummarized_articles: int = 0,
    now: datetime | None = None,
    max_age_hours: int = 24,
    new_article_count: int = 3,
) -> bool:
    """Regenerate once for a new linked source or a never-summarized event."""
    if last_summarized_at is None:
        return True
    del latest_observation, previous_counts, now, max_age_hours, new_article_count
    return unsummarized_articles > 0
