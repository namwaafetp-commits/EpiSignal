import pytest
from pydantic import ValidationError

from episignal_backend.ai.schema import Extraction, GroundedCount, GroundedFlag


def minimal(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "signal_type": "outbreak_report",
        "summary": "Health authorities report a cholera outbreak in Luanda province.",
        "disease": {"name": "Cholera", "confidence": 0.97},
        "pathogen": None,
        "locations": [{"role": "primary", "country": "Angola", "place_name": "Luanda"}],
        "epidemiology": {
            "confirmed_cases": {"value": 327, "source_span": "327 confirmed cases"}
        },
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
        Extraction.model_validate(
            minimal(locations=[{"role": "somewhere", "country": "Angola"}])
        )


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
