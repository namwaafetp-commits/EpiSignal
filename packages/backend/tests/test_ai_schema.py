import pytest
from episignal_backend.ai.schema import (
    BRIEF_SLOT_COUNT,
    BRIEF_SLOTS,
    BriefPoint,
    BriefSlot,
    Extraction,
    GroundedCount,
    GroundedFlag,
)
from pydantic import ValidationError


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
        BriefPoint.model_validate({"slot": "vibes", "text": "Something happened.", "reported": True})



def minimal(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "signal_type": "outbreak_report",
        "summary": "Health authorities report a cholera outbreak in Luanda province.",
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


def test_a_grounded_extraction_validates() -> None:
    extraction = Extraction.model_validate(minimal())

    assert extraction.disease is not None
    assert extraction.disease.name == "Cholera"
    assert extraction.epidemiology.confirmed_cases == GroundedCount(
        value=327, source_span="327 confirmed cases"
    )
    assert extraction.epidemiology.deaths is None


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(create_or_update_event=True))


def test_a_count_without_a_span_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GroundedCount.model_validate({"value": 327, "source_span": "   "})


def test_a_negative_count_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GroundedCount.model_validate({"value": -1, "source_span": "minus one case"})


def test_a_flag_without_a_span_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GroundedFlag.model_validate({"value": True, "source_span": ""})


def test_an_unknown_signal_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(signal_type="football_match"))


def test_an_unknown_location_role_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(locations=[{"role": "somewhere", "country": "Angola"}]))


def test_confidence_outside_zero_to_one_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(confidence=1.4))


def test_a_summary_longer_than_the_bound_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(summary="a" * 401))


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
                    "is_public_health_relevant": True,
                    "signal_type": "outbreak_report",
                    "relevance": 0.88,
                }
            ]
        }
    )

    assert len(response.results) == 1
    assert response.results[0].relevance == 0.88


def test_a_classification_verdict_with_an_unparseable_id_is_rejected() -> None:
    from episignal_backend.ai.schema import ClassificationResponse

    with pytest.raises(ValidationError):
        ClassificationResponse.model_validate(
            {
                "results": [
                    {
                        "id": "the first one",
                        "is_public_health_relevant": True,
                        "signal_type": "outbreak_report",
                        "relevance": 0.88,
                    }
                ]
            }
        )


def test_a_classification_response_with_no_results_is_rejected() -> None:
    from episignal_backend.ai.schema import ClassificationResponse

    with pytest.raises(ValidationError):
        ClassificationResponse.model_validate({"results": []})
