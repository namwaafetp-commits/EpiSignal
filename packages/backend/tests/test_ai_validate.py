"""Validation tests for the simplified model response contracts."""

import json

import pytest
from episignal_backend.ai.validate import Rejected, validate_classification, validate_extraction


def test_valid_identity_response_is_accepted() -> None:
    value = validate_extraction(
        json.dumps(
            {"disease": "measles", "locations": [{"town": "Cebu", "country": "Philippines"}]}
        )
    )
    assert value.disease == "measles"
    assert value.locations[0].town == "Cebu"


@pytest.mark.parametrize(
    "payload",
    [
        {"disease": "dengue", "locations": [], "cases": 3},
        {"disease": "dengue", "locations": [{"town": "Cebu", "country": "PH", "admin1": "Cebu"}]},
        {"disease": "dengue"},
        {"locations": []},
    ],
)
def test_retired_or_missing_identity_keys_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(Rejected):
        validate_extraction(json.dumps(payload))


def test_null_disease_and_empty_locations_are_valid() -> None:
    value = validate_extraction(json.dumps({"disease": None, "locations": []}))
    assert value.disease is None
    assert value.locations == ()


def test_classification_accepts_only_one_relevance_verdict() -> None:
    verdict = validate_classification(json.dumps({"relevant": True, "confidence": 0.8}))
    assert verdict.relevant is True
    with pytest.raises(Rejected):
        validate_classification(json.dumps({"results": [{"relevant": True, "confidence": 0.8}]}))
