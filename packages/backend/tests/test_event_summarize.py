"""DeepSeek event-summary and material-change tests."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from episignal_backend.ai.documents import ChatResponse, ModelSpec
from episignal_backend.db.types import AiProvider, AiPurpose
from episignal_backend.events.documents import EventForSummary, SummarySource
from episignal_backend.events.summarize import (
    EventSummaryVerdict,
    FlexibleEventSummary,
    SummaryOutcome,
    configure_summary,
    has_usable_summary_source,
    pick_representative_sources,
    render_event_flash_brief,
    run_summary,
    should_resummarize,
)

NOW = datetime(2026, 9, 2, tzinfo=UTC)


def spec() -> ModelSpec:
    return ModelSpec(
        id=uuid4(),
        tier=1,
        model_id="deepseek/deepseek-v4-flash-0731",
        label="DeepSeek V4 Flash",
        provider=AiProvider.OPENROUTER,
        purpose=AiPurpose.EVENT_SUMMARY,
        prompt_price_per_million=Decimal("0"),
        completion_price_per_million=Decimal("0"),
    )


def event() -> EventForSummary:
    return EventForSummary(event_id=uuid4(), public_id="EVT-1", disease="dengue", location="Cebu")


def source(text: str, *, title: str = "Dengue report") -> SummarySource:
    return SummarySource(
        signal_id=uuid4(),
        title=title,
        source_name="WHO",
        is_official=True,
        published_at=NOW,
        article_text=text,
    )


def valid_answer() -> str:
    return json.dumps(
        {
            "title": "Dengue activity in Cebu",
            "bullets": [
                "Three cases were reported by health officials in Cebu during the latest "
                "surveillance update.",
                "Two deaths were reported, while investigators continue reviewing the "
                "affected people and circumstances.",
                "The article describes an active case investigation but does not report a "
                "confirmed transmission route.",
            ],
        }
    )


class Model:
    def __init__(self, answer: str = valid_answer()) -> None:
        self.answer = answer
        self.request = None

    def complete(self, request):
        self.request = request
        return ChatResponse(content=self.answer, latency_ms=1)


class EvidenceAwareModel:
    def __init__(self) -> None:
        self.request = None

    def complete(self, request):
        self.request = request
        payload = json.loads(request.user)
        article = payload["sources"][0]["article_text"]
        assert "42 confirmed cases" in article
        assert "2 deaths" in article
        assert "mosquito transmission" in article
        assert "response teams" in article
        assert "20 August 2026" in article
        return ChatResponse(
            content=json.dumps(
                {
                    "title": "Dengue activity in Cebu",
                    "bullets": [
                        "42 confirmed cases were reported in Cebu on 20 August 2026.",
                        "Two deaths were reported alongside the confirmed cases in this update.",
                        "Mosquito transmission was reported as the suspected route in the article.",
                        "Response teams were deployed to investigate and control the "
                        "reported event.",
                    ],
                }
            ),
            latency_ms=1,
        )


def test_summary_uses_linked_article_text_and_mistral_route() -> None:
    model = Model()
    result = run_summary(
        model, spec(), event=event(), sources=(source("Three cases and two deaths."),)
    )
    assert result.outcome is SummaryOutcome.ACCEPTED
    assert model.request.model_id == "deepseek/deepseek-v4-flash-0731"
    payload = json.loads(model.request.user)
    assert payload["sources"][0]["article_text"] == "Three cases and two deaths."
    assert "brief" not in payload["sources"][0]


def test_summary_evidence_is_article_grounded_for_counts_transmission_response_and_dates() -> None:
    model = EvidenceAwareModel()
    article = (
        "On 20 August 2026, the ministry confirmed 42 confirmed cases and 2 deaths. "
        "Investigators reported mosquito transmission, and response teams were deployed."
    )
    result = run_summary(model, spec(), event=event(), sources=(source(article),))
    assert result.outcome is SummaryOutcome.ACCEPTED
    assert isinstance(result.verdict, FlexibleEventSummary)
    assert "42 confirmed cases were reported in Cebu on 20 August 2026." in result.verdict.bullets
    assert (
        "Response teams were deployed to investigate and control the reported event."
        in result.verdict.bullets
    )


def test_new_summary_uses_existing_event_heading_and_renders_flexible_contract() -> None:
    current = event().model_copy(update={"headline": "Canonical event title"})
    result = run_summary(Model(), spec(), event=current, sources=(source("Report"),))
    assert isinstance(result.verdict, FlexibleEventSummary)
    assert result.verdict.title == "Canonical event title"
    rendered = render_event_flash_brief(result.verdict)
    assert "• Three cases" in rendered
    assert "Takeaway:" not in rendered
    assert "Key Driver:" not in rendered


def test_legacy_shaped_model_output_is_rejected_for_new_summary_requests() -> None:
    answer = json.dumps(
        {
            "headline": "x",
            "trajectory": "Unclear",
            "snapshot": ["No cases reported"],
            "key_driver": "Not yet established.",
            "response": "No specific response reported.",
            "risk": "Insufficient evidence for a broader risk assessment.",
        }
    )
    result = run_summary(Model(answer), spec(), event=event(), sources=(source("No count."),))
    assert result.outcome is SummaryOutcome.REJECTED
    assert result.verdict is None


def test_historical_legacy_summary_still_renders_with_legacy_headings() -> None:
    verdict = EventSummaryVerdict(
        headline="Dengue Outbreak: Cebu — Increasing",
        trajectory="Increasing",
        snapshot=("Three cases", "Two deaths"),
        key_driver="Rainfall",
        response="Case investigation",
        risk="Regional risk",
    )

    rendered = render_event_flash_brief(verdict)

    assert "The Snapshot:" in rendered
    assert "Key Driver:" in rendered
    assert "Public/Global Risk:" in rendered


def test_no_unsummarized_linked_article_does_not_trigger_resummary() -> None:
    assert (
        should_resummarize(
            last_summarized_at=NOW,
            latest_observation=None,
            previous_counts=None,
            unsummarized_articles=0,
            now=NOW,
        )
        is False
    )
    assert (
        should_resummarize(
            last_summarized_at=NOW,
            latest_observation=None,
            previous_counts=None,
            unsummarized_articles=1,
            now=NOW,
        )
        is False
    )
    assert (
        should_resummarize(
            last_summarized_at=NOW,
            latest_observation=None,
            previous_counts=None,
            unsummarized_articles=3,
            now=NOW,
        )
        is True
    )


def test_never_summarized_event_is_due() -> None:
    assert should_resummarize(
        last_summarized_at=None, latest_observation=None, previous_counts=None
    )


def test_new_event_with_article_text_is_eligible_without_structured_observation() -> None:
    current = event().model_copy(
        update={
            "disease": "",
            "location": "",
            "latest_observation": None,
            "previous_counts": None,
            "sources": (source("Officials are investigating an unusual illness."),),
        }
    )

    assert current.last_summarized_at is None
    assert current.latest_observation is None
    assert has_usable_summary_source(current.sources)
    assert should_resummarize(
        last_summarized_at=current.last_summarized_at,
        latest_observation=current.latest_observation,
        previous_counts=current.previous_counts,
    )


def test_new_event_with_unresolved_identity_and_article_text_is_eligible() -> None:
    current = event().model_copy(
        update={
            "disease": "",
            "location": "Unresolved location",
            "sources": (source("A suspected outbreak is under investigation."),),
        }
    )

    assert should_resummarize(
        last_summarized_at=current.last_summarized_at,
        latest_observation=current.latest_observation,
        previous_counts=current.previous_counts,
    )
    assert has_usable_summary_source(current.sources)


def test_event_without_usable_article_text_is_not_eligible_for_summary() -> None:
    assert not has_usable_summary_source((source("   "),))


def test_existing_event_with_material_observation_change_is_due() -> None:
    assert should_resummarize(
        last_summarized_at=NOW,
        latest_observation={"material_facts": {"cases": 4}},
        previous_counts={"material_facts": {"cases": 3}},
        unsummarized_articles=0,
        now=NOW,
    )


def test_deepseek_summary_wiring_uses_openrouter_registry_route() -> None:
    from episignal_backend.config import Settings

    settings = Settings(
        database_url="postgresql://user:secret@host/db",
        openrouter_api_key="openrouter-test-key",
        _env_file=None,
    )

    wiring = configure_summary(settings, [spec()])

    assert wiring.model is not None
    assert wiring.spec is not None
    assert wiring.spec.model_id == "deepseek/deepseek-v4-flash-0731"
    assert wiring.spec.provider is AiProvider.OPENROUTER


def test_representative_sources_are_official_then_recent_and_article_backed() -> None:
    old = SummarySource(
        signal_id=uuid4(),
        title="old",
        source_name="blog",
        is_official=False,
        published_at=datetime(2026, 8, 1, tzinfo=UTC),
        article_text="",
    )
    new = source("Article text", title="new")
    assert pick_representative_sources((old, new), max_sources=1) == (new,)


def test_malformed_or_unavailable_summary_is_not_accepted() -> None:
    assert (
        run_summary(Model("not json"), spec(), event=event(), sources=(source("Report"),)).outcome
        is SummaryOutcome.REJECTED
    )

    class Unavailable:
        def complete(self, request):
            from episignal_backend.ai.protocol import ModelUnavailable

            raise ModelUnavailable("429")

    unavailable = run_summary(Unavailable(), spec(), event=event(), sources=(source("Report"),))
    assert unavailable.outcome is SummaryOutcome.UNAVAILABLE
    assert unavailable.failure_exception_class == "ModelUnavailable"
    assert unavailable.failure_reason == "429"


def test_unavailable_summary_diagnostic_is_case_identifiable_and_sanitized() -> None:
    class Unavailable:
        def complete(self, request):
            from episignal_backend.ai.protocol import ModelUnavailable

            raise ModelUnavailable("api_key=secret full provider response should not persist")

    from episignal_backend.events.summarize import build_summary_failure_diagnostic

    current_event = event()
    result = run_summary(Unavailable(), spec(), event=current_event, sources=(source("Report"),))
    diagnostic = build_summary_failure_diagnostic(current_event, result, at=NOW)

    assert diagnostic is not None
    assert diagnostic["event_id"] == current_event.public_id
    assert diagnostic["category"] == "provider_unavailable"
    assert diagnostic["exception_class"] == "ModelUnavailable"
    assert diagnostic["provider"] == "openrouter"
    assert diagnostic["model"] == spec().model_id
    assert "secret" not in str(diagnostic)
    assert "provider response" in diagnostic["message"]


def test_unavailable_summary_diagnostic_keeps_provider_retry_metadata() -> None:
    class Unavailable:
        def complete(self, request):
            from episignal_backend.ai.protocol import ModelUnavailable

            raise ModelUnavailable("429", attempts=2, http_status=429)

    from episignal_backend.events.summarize import build_summary_failure_diagnostic

    current_event = event()
    result = run_summary(Unavailable(), spec(), event=current_event, sources=(source("Report"),))
    diagnostic = build_summary_failure_diagnostic(current_event, result, at=NOW)

    assert diagnostic is not None
    assert diagnostic["category"] == "http_429"
    assert diagnostic["retry_count"] == 1
    assert diagnostic["provider_status_class"] == "4xx"


def test_summary_verdict_keeps_one_to_three_article_facts() -> None:
    assert EventSummaryVerdict(
        headline="x",
        trajectory="Stable",
        snapshot=("case",),
        key_driver="x",
        response="x",
        risk="x",
    ).snapshot == ("case",)


def test_flexible_summary_accepts_three_and_five_bullets_and_renders_without_headings() -> None:
    for count in (3, 5):
        verdict = FlexibleEventSummary(
            title="Dengue reports rise in Cebu",
            bullets=tuple(
                f"Supported epidemiological fact {index} is documented in the linked "
                "surveillance report."
                for index in range(count)
            ),
        )
        rendered = render_event_flash_brief(verdict)
        assert rendered.startswith("Dengue reports rise in Cebu")
        assert rendered.count("•") == count
        assert "Takeaway:" not in rendered
        assert "Key Driver:" not in rendered


def test_flexible_summary_rejects_invalid_bullet_counts_and_blank_text() -> None:
    import pytest

    with pytest.raises(ValueError):
        FlexibleEventSummary(title="Title", bullets=("one", "two"))
    with pytest.raises(ValueError):
        FlexibleEventSummary(
            title="Title",
            bullets=tuple(f"fact {index}" for index in range(6)),
        )
    with pytest.raises(ValueError):
        FlexibleEventSummary(title=" ", bullets=("one", "two", "three"))
    with pytest.raises(ValueError):
        FlexibleEventSummary(title="Title", bullets=("one", "two", "three"), takeaway=" ")


def test_new_summary_contract_uses_existing_event_headline_as_title() -> None:
    current = event().model_copy(update={"headline": "Canonical event title"})
    model = Model(
        json.dumps(
            {
                "title": "Model title",
                "bullets": [
                    "First supported fact is described in the linked infectious disease "
                    "surveillance report.",
                    "Second supported fact is described in the linked infectious disease "
                    "surveillance report.",
                    "Third supported fact is described in the linked infectious disease "
                    "surveillance report.",
                ],
            }
        )
    )
    result = run_summary(model, spec(), event=current, sources=(source("Report"),))
    assert result.outcome is SummaryOutcome.ACCEPTED
    assert isinstance(result.verdict, FlexibleEventSummary)
    assert result.verdict.title == "Canonical event title"
