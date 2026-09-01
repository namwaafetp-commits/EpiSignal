import pytest
from episignal_backend.ai.schema import (
    BACKFILL_MIN_SCHEMA_VERSION,
    BRIEF_SLOT_COUNT,
    BRIEF_SLOTS,
    EXTRACTION_SCHEMA_VERSION,
    EXTRACTION_VERSION_KEY,
    BriefPoint,
    BriefSlot,
    Extraction,
    GroundedCount,
    StoredExtractionPayload,
    TriageVerdict,
)
from pydantic import ValidationError


def test_a_triage_verdict_allows_every_fact_to_be_missing() -> None:
    verdict = TriageVerdict.model_validate(
        {"relevant": True, "public_health": True, "confidence": 0.9}
    )

    assert verdict.disease is None
    assert verdict.country is None
    assert verdict.admin1 is None


def test_a_two_letter_country_is_required_when_present() -> None:
    with pytest.raises(ValidationError):
        TriageVerdict.model_validate(
            {
                "relevant": True,
                "public_health": True,
                "confidence": 0.9,
                "country": "Thailand",
            }
        )


def test_an_empty_string_is_read_as_missing() -> None:
    verdict = TriageVerdict.model_validate(
        {
            "relevant": True,
            "public_health": True,
            "confidence": 0.9,
            "admin1": "  ",
        }
    )

    assert verdict.admin1 is None


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ValidationError):
        TriageVerdict.model_validate(
            {
                "relevant": True,
                "public_health": True,
                "confidence": 0.9,
                "severity": "high",
            }
        )


def test_the_slots_are_ordered_as_an_epidemiologist_reads_them() -> None:
    assert BRIEF_SLOTS == (
        BriefSlot.WHAT_WHERE,
        BriefSlot.COUNTS,
        BriefSlot.TIMING,
        BriefSlot.SPREAD,
        BriefSlot.REPORTING,
    )
    assert BRIEF_SLOT_COUNT == 5


def test_a_point_may_report_an_absence() -> None:
    point = BriefPoint.model_validate(
        {"slot": "counts", "text": "No case count reported.", "reported": False}
    )

    assert point.reported is False
    assert point.slot is BriefSlot.COUNTS


def test_a_point_must_say_something_even_when_nothing_was_reported() -> None:
    with pytest.raises(ValidationError):
        BriefPoint.model_validate({"slot": "counts", "text": "   ", "reported": False})


def test_a_point_rejects_a_slot_nobody_defined() -> None:
    with pytest.raises(ValidationError):
        BriefPoint.model_validate(
            {"slot": "vibes", "text": "Something happened.", "reported": True}
        )


def brief() -> list[dict[str, object]]:
    return [
        {"slot": "what_where", "text": "Cholera in Luanda province, Angola.", "reported": True},
        {"slot": "counts", "text": "327 confirmed cases and 14 deaths.", "reported": True},
        {"slot": "timing", "text": "Figures are as of 25 August 2026.", "reported": True},
        {"slot": "spread", "text": "All cases were acquired locally.", "reported": True},
        {
            "slot": "reporting",
            "text": "Reported by Angola's health ministry.",
            "reported": True,
        },
    ]


def minimal(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "signal_type": "outbreak_report",
        "source_language": "en",
        "title_english": "Angola reports growing cholera outbreak in Luanda",
        "brief": brief(),
        "disease": {"name": "Cholera", "confidence": 0.97},
        "pathogen": None,
        "locations": [{"role": "primary", "country": "Angola", "place_name": "Luanda"}],
        "epidemiology": {"confirmed_cases": {"value": 327, "source_span": "327 confirmed cases"}},
        "dates": {"data_as_of": "2026-08-25"},
        "transmission": None,
        "confidence": 0.94,
    }
    payload.update(overrides)
    return payload


def test_an_extraction_carries_an_english_title_and_five_bullets() -> None:
    extraction = Extraction.model_validate(minimal())

    assert extraction.title_english == "Angola reports growing cholera outbreak in Luanda"
    assert extraction.source_language == "en"
    assert tuple(point.slot for point in extraction.brief) == BRIEF_SLOTS


def test_a_brief_missing_a_slot_is_rejected() -> None:
    short = brief()[:4]

    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(brief=short))


def test_a_brief_with_a_repeated_slot_is_rejected() -> None:
    repeated = brief()
    repeated[3] = dict(repeated[1])

    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(brief=repeated))


def test_a_brief_out_of_slot_order_is_rejected_rather_than_sorted() -> None:
    shuffled = brief()
    shuffled[0], shuffled[1] = shuffled[1], shuffled[0]

    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(brief=shuffled))


def test_the_free_form_summary_is_no_longer_part_of_the_contract() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(summary="Cholera in Angola."))


def test_a_blank_english_title_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(title_english="   "))


def test_an_unknown_source_language_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(source_language="portuguese"))


def test_a_two_letter_code_outside_iso_639_1_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(source_language="zz"))


def test_a_known_language_code_is_normalized_to_lowercase() -> None:
    extraction = Extraction.model_validate(minimal(source_language="FR"))

    assert extraction.source_language == "fr"


def test_an_unsure_source_language_is_stored_as_absence() -> None:
    extraction = Extraction.model_validate(minimal(source_language=None))

    assert extraction.source_language is None


def test_the_prompt_schema_names_every_field_the_model_must_return() -> None:
    from episignal_backend.ai.schema import extraction_json_schema

    schema = extraction_json_schema()

    assert schema["additionalProperties"] is False
    assert "epidemiology" in schema["properties"]
    assert "confidence" in schema["properties"]


def test_a_classification_response_carries_one_verdict_per_signal() -> None:
    from episignal_backend.ai.schema import ClassificationResponse

    response = ClassificationResponse.model_validate(
        {
            "results": [
                {
                    "id": "b3f1c2d4-0000-4000-8000-000000000001",
                    "relevant": True,
                    "confidence": 0.88,
                }
            ]
        }
    )

    assert len(response.results) == 1
    assert response.results[0].confidence == 0.88


def test_classification_schema_contains_relevance_only_fields() -> None:
    from episignal_backend.ai.schema import classification_json_schema

    schema = classification_json_schema()
    properties = schema["$defs"]["ClassificationVerdict"]["properties"]
    assert set(properties) == {"id", "relevant", "confidence", "reason_code"}


def test_a_classification_verdict_with_an_unparseable_id_is_rejected() -> None:
    from episignal_backend.ai.schema import ClassificationResponse

    with pytest.raises(ValidationError):
        ClassificationResponse.model_validate(
            {
                "results": [
                    {
                        "id": "the first one",
                        "relevant": True,
                        "confidence": 0.88,
                    }
                ]
            }
        )


def test_a_classification_response_with_no_results_is_rejected() -> None:
    from episignal_backend.ai.schema import ClassificationResponse

    with pytest.raises(ValidationError):
        ClassificationResponse.model_validate({"results": []})


def test_a_stored_payload_tolerates_the_version_key_the_strict_model_forbids() -> None:
    stored = dict(minimal())
    stored[EXTRACTION_VERSION_KEY] = EXTRACTION_SCHEMA_VERSION

    payload = StoredExtractionPayload.model_validate(stored)

    assert payload.title_english == "Angola reports growing cholera outbreak in Luanda"
    assert len(payload.brief) == BRIEF_SLOT_COUNT


def test_a_row_written_before_this_item_is_still_readable() -> None:
    old = {
        "signal_type": "outbreak_report",
        "disease": {"name": "Cholera", "confidence": 0.97},
        "epidemiology": {"confirmed_cases": {"value": 327, "source_span": "327 confirmed cases"}},
        "confidence": 0.9,
    }

    payload = StoredExtractionPayload.model_validate(old)

    assert payload.brief == ()
    assert payload.title_english is None
    assert payload.epidemiology.confirmed_cases is not None


def test_a_stored_payload_is_an_extraction() -> None:
    assert isinstance(StoredExtractionPayload.model_validate(minimal()), Extraction)


def test_the_strict_model_still_refuses_the_version_key() -> None:
    stored = dict(minimal())
    stored[EXTRACTION_VERSION_KEY] = EXTRACTION_SCHEMA_VERSION

    with pytest.raises(ValidationError):
        Extraction.model_validate(stored)


V2_STORED_ROW = {
    "signal_type": "outbreak_report",
    "source_language": "en",
    "title_english": "Angola reports growing cholera outbreak in Luanda",
    "brief": [
        {"slot": "what_where", "text": "Cholera in Luanda province, Angola.", "reported": True},
        {"slot": "counts", "text": "327 confirmed cases and 14 deaths.", "reported": True},
        {"slot": "timing", "text": "Figures are as of 25 August 2026.", "reported": True},
        {"slot": "spread", "text": "All cases were acquired locally.", "reported": True},
        {
            "slot": "reporting",
            "text": "Reported by Angola's health ministry.",
            "reported": True,
        },
    ],
    "disease": {"name": "Cholera", "confidence": 0.97},
    "locations": [{"role": "primary", "country": "Angola", "place_name": "Luanda"}],
    "epidemiology": {
        "confirmed_cases": {"value": 327, "source_span": "327 confirmed cases"},
        "deaths": {"value": 14, "source_span": "14 people have died"},
    },
    "confidence": 0.94,
    "extraction_schema_version": 2,
}


def test_a_grounded_count_defaults_to_the_only_member() -> None:
    count = GroundedCount(value=12, source_span="12 confirmed cases")

    assert count.source_index == 0


def test_a_grounded_count_can_cite_a_later_member() -> None:
    count = GroundedCount(value=12, source_span="12 confirmed cases", source_index=3)

    assert count.source_index == 3


def test_a_negative_source_index_is_refused() -> None:
    with pytest.raises(ValidationError):
        GroundedCount(value=12, source_span="12 confirmed cases", source_index=-1)


def test_the_stored_version_is_three() -> None:
    assert EXTRACTION_SCHEMA_VERSION == 3


def test_the_backfill_floor_stays_at_two() -> None:
    # A v2 row is a v3 row whose every claim cites member 0, so bumping the
    # version must not re-extract the corpus.
    assert BACKFILL_MIN_SCHEMA_VERSION == 2


def test_a_version_two_row_reads_back_with_index_zero() -> None:
    payload = StoredExtractionPayload.model_validate(V2_STORED_ROW)

    assert payload.epidemiology.deaths is not None
    assert payload.epidemiology.deaths.source_index == 0
