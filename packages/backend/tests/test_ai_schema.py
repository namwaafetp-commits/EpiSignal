"""Schemas for active AI boundaries and historical row compatibility."""

import pytest
from episignal_backend.ai.schema import (
    EXTRACTION_SCHEMA_VERSION,
    Extraction,
    ExtractionLocation,
    StoredExtractionPayload,
    classification_json_schema,
    extraction_json_schema,
)


def test_extraction_accepts_disease_and_locations_only() -> None:
    value = Extraction.model_validate(
        {"disease": "dengue", "locations": [{"town": "Cebu", "country": "Philippines"}]}
    )
    assert value == Extraction(
        disease="dengue", locations=(ExtractionLocation(town="Cebu", country="Philippines"),)
    )


def test_extraction_allows_unknown_or_null_identity() -> None:
    assert Extraction(disease="novel fever", locations=()).disease == "novel fever"
    assert Extraction(disease=None, locations=()).disease is None


def test_extraction_rejects_extra_nested_keys() -> None:
    with pytest.raises(ValueError):
        Extraction.model_validate(
            {
                "disease": "dengue",
                "locations": [{"town": "Cebu", "country": "PH", "admin1": "Cebu"}],
            }
        )


def test_prompt_schema_contains_only_active_fields() -> None:
    schema = extraction_json_schema()
    assert set(schema["properties"]) == {"disease", "locations"}
    assert set(schema["properties"]["locations"]["items"]["properties"]) == {"town", "country"}


def test_classification_schema_is_relevance_only() -> None:
    assert set(classification_json_schema()["properties"]) == {
        "relevant",
        "confidence",
        "reason_code",
    }


def test_historical_payload_with_deprecated_fields_remains_readable() -> None:
    payload = StoredExtractionPayload.model_validate(
        {
            "schema_version": 2,
            "disease_text": "Dengue",
            "locations": [{"country_code": "TH", "place_name": "Chiang Mai"}],
            "epidemiology": {"confirmed_cases": {"value": 12}},
        }
    )
    assert payload.disease == "Dengue"
    assert payload.locations[0].country == "TH"
    assert payload.locations[0].town == "Chiang Mai"


def test_current_schema_version_is_new_identity_version() -> None:
    assert EXTRACTION_SCHEMA_VERSION == 5
