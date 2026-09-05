"""Acceptance tests for the final three-model surveillance pipeline."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from episignal_backend.ai.documents import (
    ChatResponse,
    ExtractableSignal,
    ModelSpec,
)
from episignal_backend.ai.extract import extract_signal
from episignal_backend.ai.ladder import Guards, RunBudget
from episignal_backend.ai.prompts import (
    GEMINI_EXTRACTION_PROMPT,
    IDENTITY_REPAIR,
    extraction_prompt,
)
from episignal_backend.ai.registry import model_for_purpose
from episignal_backend.ai.schema import Extraction, ExtractionLocation, extraction_json_schema
from episignal_backend.ai.validate import Rejected, validate_extraction
from episignal_backend.db.types import (
    AiProvider,
    AiPurpose,
    CredibilityTier,
    LocationRole,
    Precision,
)
from episignal_backend.events.cluster import compatible
from episignal_backend.events.documents import (
    EventForSummary,
    LocationForMatching,
    SignalForMatching,
    SummarySource,
)
from episignal_backend.events.summarize import run_summary, should_resummarize


def _spec(model_id: str, provider: AiProvider, purpose: AiPurpose) -> ModelSpec:
    return ModelSpec(
        id=uuid4(),
        tier=1,
        model_id=model_id,
        label=model_id,
        provider=provider,
        purpose=purpose,
        prompt_price_per_million=Decimal("0"),
        completion_price_per_million=Decimal("0"),
    )


@pytest.mark.parametrize(
    ("purpose", "model_id", "provider"),
    [
        (AiPurpose.CLASSIFICATION, "deepseek/deepseek-v4-flash-0731", AiProvider.OPENROUTER),
        (AiPurpose.EXTRACTION, "google/gemini-3.1-flash-lite", AiProvider.GEMINI),
        (
            AiPurpose.EVENT_SUMMARY,
            "mistralai/mistral-small-3.2-24b-instruct",
            AiProvider.OPENROUTER,
        ),
    ],
)
def test_purpose_registry_selects_exact_final_model(
    purpose: AiPurpose, model_id: str, provider: AiProvider
) -> None:
    wanted = _spec(model_id, provider, purpose)
    noise = _spec("other/model", provider, purpose)
    assert model_for_purpose((noise, wanted), purpose) == wanted


def test_extraction_schema_contains_only_disease_and_locations() -> None:
    schema = extraction_json_schema()
    assert set(schema["properties"]) == {"disease", "locations"}
    assert set(schema["properties"]["locations"]["items"]["properties"]) == {"town", "country"}


def test_extraction_rejects_extra_nested_location_keys() -> None:
    with pytest.raises(Rejected):
        validate_extraction(
            json.dumps(
                {
                    "disease": "dengue",
                    "locations": [{"town": "Cebu", "country": "PH", "extra": "x"}],
                }
            )
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"disease": "measles", "locations": [{"town": "Cebu", "country": "Philippines"}]},
        {"disease": "dengue", "locations": [{"town": None, "country": "Thailand"}]},
        {
            "disease": "H5N1 avian influenza",
            "locations": [
                {"town": "Cebu", "country": "Philippines"},
                {"town": "Dhaka", "country": "Bangladesh"},
            ],
        },
        {
            "disease": "novel febrile illness",
            "locations": [{"town": "Beni", "country": "DR Congo"}],
        },
        {"disease": None, "locations": [{"town": "Cebu", "country": "Philippines"}]},
        {"disease": "measles", "locations": []},
    ],
)
def test_extraction_accepts_required_identity_shapes(payload: dict[str, object]) -> None:
    value = Extraction.model_validate(payload)
    assert value.disease == payload["disease"]
    assert [location.model_dump(mode="json") for location in value.locations] == payload[
        "locations"
    ]


def test_production_gemini_prompt_uses_title_and_clean_article() -> None:
    signal = ExtractableSignal(
        id=uuid4(), title="Measles in Cebu", raw_text="Three cases were reported."
    )
    system, user = extraction_prompt(signal, max_characters=1000)
    assert system == GEMINI_EXTRACTION_PROMPT.replace("<title>", signal.title).replace(
        "<clean article body>", signal.raw_text
    )
    assert user == "Return the extraction JSON."


class _ScriptedModel:
    def __init__(self, answers: list[dict[str, object]]) -> None:
        self.answers = list(answers)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return ChatResponse(content=json.dumps(self.answers.pop(0)), latency_ms=1)


def _extract(answers: list[dict[str, object]]):
    model = _ScriptedModel(answers)
    spec = _spec("google/gemini-3.1-flash-lite", AiProvider.GEMINI, AiPurpose.EXTRACTION)
    result = extract_signal(
        ExtractableSignal(
            id=uuid4(), title="Measles in Cebu", raw_text="Measles was reported in Cebu."
        ),
        model,
        spec=spec,
        budget=RunBudget(Guards(max_requests=5, max_cost_usd=Decimal("1"))),
    )
    return result, model


def test_extraction_accepts_complete_identity_without_retry() -> None:
    result, model = _extract(
        [{"disease": "measles", "locations": [{"town": "Cebu", "country": "Philippines"}]}]
    )
    assert result.extraction == Extraction(
        disease="measles",
        locations=(ExtractionLocation(town="Cebu", country="Philippines"),),
    )
    assert len(model.requests) == 1


@pytest.mark.parametrize(
    "first",
    [
        {"disease": None, "locations": [{"town": "Cebu", "country": "Philippines"}]},
        {"disease": "measles", "locations": [{"town": "Cebu", "country": None}]},
    ],
)
def test_extraction_repairs_missing_identity_once(first: dict[str, object]) -> None:
    repaired = {"disease": "measles", "locations": [{"town": "Cebu", "country": "Philippines"}]}
    result, model = _extract([first, repaired])
    assert result.extraction == Extraction.model_validate(repaired)
    assert len(model.requests) == 2
    assert model.requests[0].model_id == model.requests[1].model_id
    assert IDENTITY_REPAIR in model.requests[1].system


def test_extraction_retries_at_most_once_and_keeps_best_partial() -> None:
    first = {"disease": "measles", "locations": [{"town": "Cebu", "country": None}]}
    second = {"disease": None, "locations": [{"town": None, "country": None}]}
    result, model = _extract([first, second])
    assert result.extraction == Extraction.model_validate(first)
    assert len(model.requests) == 2


def test_extraction_retry_keeps_a_better_partial_identity() -> None:
    result, model = _extract(
        [
            {"disease": None, "locations": []},
            {"disease": "measles", "locations": [{"town": "Cebu", "country": None}]},
        ]
    )
    assert result.extraction is not None
    assert result.extraction.disease == "measles"
    assert len(model.requests) == 2


def _location(town: str | None, country: str) -> LocationForMatching:
    return LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE if town else Precision.COUNTRY,
        country_code=country,
        place_name=town,
    )


def _signal(
    disease_text: str,
    locations: tuple[LocationForMatching, ...],
    *,
    at: datetime | None = None,
) -> SignalForMatching:
    moment = at or datetime(2026, 9, 2, tzinfo=UTC)
    return SignalForMatching(
        signal_id=uuid4(),
        disease_text=disease_text,
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=moment,
        first_seen_at=moment,
        locations=locations,
    )


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ((_location("Cebu", "PH"),), (_location(" cebu ", "PH"),), True),
        ((_location("Cebu", "PH"),), (_location("Manila", "PH"),), False),
        ((_location(None, "PH"),), (_location(None, "PH"),), True),
        ((_location(None, "PH"),), (_location("Cebu", "PH"),), False),
        (
            (_location("Cebu", "PH"), _location("Dhaka", "BD")),
            (_location("Dhaka", "BD"),),
            True,
        ),
        (
            (_location("Cebu", "PH"), _location("Dhaka", "BD")),
            (_location("Manila", "PH"),),
            False,
        ),
    ],
)
def test_grouping_uses_exact_compatible_location_overlap(left, right, expected: bool) -> None:
    assert compatible(_signal("dengue", left), _signal(" dengue ", right)) is expected


def test_grouping_keeps_different_unknown_disease_text_separate() -> None:
    locations = (_location("Cebu", "PH"),)
    assert not compatible(
        _signal("unknown fever a", locations), _signal("unknown fever b", locations)
    )


def test_grouping_retains_time_window() -> None:
    locations = (_location("Cebu", "PH"),)
    first = _signal("dengue", locations)
    late = _signal("dengue", locations, at=first.first_seen_at + timedelta(days=15))
    assert not compatible(first, late, window_days=14)


def test_summary_sends_linked_article_text_and_not_legacy_brief() -> None:
    class SummaryModel:
        def __init__(self) -> None:
            self.request = None

        def complete(self, request):
            self.request = request
            return ChatResponse(
                content=json.dumps(
                    {
                        "headline": "Dengue Outbreak: Cebu — Increasing",
                        "trajectory": "Increasing",
                        "snapshot": ["Three cases reported"],
                        "key_driver": "Not yet established.",
                        "response": "No specific response reported.",
                        "risk": "Insufficient evidence for a broader risk assessment.",
                    }
                ),
                latency_ms=1,
            )

    model = SummaryModel()
    spec = _spec(
        "mistralai/mistral-small-3.2-24b-instruct",
        AiProvider.OPENROUTER,
        AiPurpose.EVENT_SUMMARY,
    )
    event = EventForSummary(
        event_id=uuid4(),
        public_id="EVT-1",
        disease="dengue",
        location="Cebu",
    )
    source = SummarySource(
        signal_id=uuid4(),
        title="Dengue cases in Cebu",
        source_name="WHO",
        article_text="Three cases were reported in Cebu.",
    )
    result = run_summary(model, spec, event=event, sources=(source,))
    assert result.outcome.value == "accepted"
    payload = json.loads(model.request.user)
    assert payload["sources"][0]["article_text"] == source.article_text
    assert "brief" not in payload["sources"][0]


def test_summary_is_due_for_new_linked_article_only() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    assert should_resummarize(
        last_summarized_at=now,
        latest_observation=None,
        previous_counts=None,
        unsummarized_articles=1,
    )
    assert not should_resummarize(
        last_summarized_at=now,
        latest_observation=None,
        previous_counts=None,
        unsummarized_articles=0,
    )
