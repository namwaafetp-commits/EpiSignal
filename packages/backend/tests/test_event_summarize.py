"""Mistral event-summary and material-change tests."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from episignal_backend.ai.documents import ChatResponse, ModelSpec
from episignal_backend.db.types import AiProvider, AiPurpose
from episignal_backend.events.documents import EventForSummary, SummarySource
from episignal_backend.events.summarize import (
    EventSummaryVerdict,
    SummaryOutcome,
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
        model_id="mistralai/mistral-small-3.2-24b-instruct",
        label="Mistral Small 3.2",
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
            "headline": "ignored by canonicalizer",
            "trajectory": "Increasing",
            "snapshot": ["Three cases", "Two deaths"],
            "key_driver": "Rainfall",
            "response": "Case investigation",
            "risk": "Regional risk",
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
                    "headline": "ignored",
                    "trajectory": "Increasing",
                    "snapshot": [
                        "42 confirmed cases on 20 August 2026",
                        "2 deaths",
                        "Mosquito transmission reported",
                    ],
                    "key_driver": "Mosquito transmission",
                    "response": "Response teams were deployed.",
                    "risk": "Regional risk",
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
    assert model.request.model_id == "mistralai/mistral-small-3.2-24b-instruct"
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
    assert result.verdict is not None
    assert "42 confirmed cases on 20 August 2026" in result.verdict.snapshot
    assert result.verdict.response == "Response teams were deployed."


def test_summary_canonicalizes_event_heading_and_renders_contract() -> None:
    result = run_summary(Model(), spec(), event=event(), sources=(source("Report"),))
    assert result.verdict is not None
    assert result.verdict.headline == "Dengue Outbreak: Cebu — Increasing"
    rendered = render_event_flash_brief(result.verdict)
    assert "The Snapshot:" in rendered and "Key Driver:" in rendered


def test_summary_uses_fixed_fallbacks_from_model_output() -> None:
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
    assert result.outcome is SummaryOutcome.ACCEPTED
    assert result.verdict is not None and result.verdict.key_driver == "Not yet established."


def test_no_unsummarized_linked_article_does_not_trigger_resummary() -> None:
    assert (
        should_resummarize(
            last_summarized_at=NOW,
            latest_observation=None,
            previous_counts=None,
            unsummarized_articles=0,
        )
        is False
    )
    assert (
        should_resummarize(
            last_summarized_at=NOW,
            latest_observation=None,
            previous_counts=None,
            unsummarized_articles=1,
        )
        is True
    )


def test_never_summarized_event_is_due() -> None:
    assert should_resummarize(
        last_summarized_at=None, latest_observation=None, previous_counts=None
    )


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
