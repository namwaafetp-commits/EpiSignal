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
from episignal_backend.ai.protocol import ChatModel, ModelUnavailable
from episignal_backend.ai.validate import Rejected, RejectionReason
from episignal_backend.config import Settings
from episignal_backend.db.types import AiOutcome, AiPurpose
from episignal_backend.events.documents import EventForSummary, SummarySource

SUMMARY_SCHEMA_NAME = "event_summary"
SUMMARY_TEMPERATURE = 0.0

SUMMARY_SYSTEM = (
    "You write one EpiSignal epidemiological event flash brief from all linked "
    "event observations and sources.\n"
    "Rules:\n"
    "- Summarize the EVENT, never an individual article. Use all observations and "
    "prefer the newest credible figures.\n"
    "- Preserve confirmed, suspected, and probable distinctions.\n"
    "- Every number, disease, location, transmission claim, response, and risk "
    "claim must be supported by the supplied evidence. Never invent or silently "
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
    "- Snapshot values are concise evidence-grounded strings or null.\n\n"
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


class SummarySnapshot(BaseModel):
    """The evidence snapshot rendered in the flash brief."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Keep every contract key present even when evidence is absent. A missing
    # key would make old and new payloads indistinguishable at the boundary;
    # explicit null preserves the evidence distinction required by the brief.
    cases: str | None
    deaths: str | None
    cfr: str | None
    geographic_extent: str | None

    @field_validator("cases", "deaths", "cfr", "geographic_extent")
    @classmethod
    def blank_is_null(cls, value: str | None) -> str | None:
        if value is None:
            return None
        collapsed = " ".join(value.split())
        return collapsed or None


class EventSummaryVerdict(BaseModel):
    """The summarizer's answer, validated strictly."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    headline: str = Field(min_length=1)
    trajectory: SummaryTrajectory
    snapshot: SummarySnapshot
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
    snapshot = verdict.snapshot
    deaths_or_cfr = snapshot.deaths or snapshot.cfr or "Not reported"
    if snapshot.deaths is not None and snapshot.cfr is not None:
        deaths_or_cfr = f"{snapshot.deaths} / {snapshot.cfr}"
    return "\n\n".join(
        (
            verdict.headline,
            "The Snapshot:\n"
            f"{snapshot.cases or 'Not reported'} | {deaths_or_cfr} | "
            f"{snapshot.geographic_extent or 'Not reported'}",
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
    """Decide whether a new event observation materially changes its brief.

    The legacy article-count and age arguments remain accepted for callers that
    have not migrated, but neither can trigger a new event summary.
    """
    if last_summarized_at is None:
        return True
    return not _counts_equals(latest_observation, previous_counts)
