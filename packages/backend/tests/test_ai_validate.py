import json

import pytest

from episignal_backend.ai.schema import Extraction
from episignal_backend.ai.validate import RejectionReason, Rejected, parse_extraction

GROUNDED = {
    "signal_type": "outbreak_report",
    "summary": "Cholera outbreak reported in Luanda.",
    "disease": {"name": "Cholera", "confidence": 0.97},
    "epidemiology": {
        "confirmed_cases": {"value": 327, "source_span": "327 confirmed cases"},
        "total_cases": {"value": 400, "source_span": "400 cases in total"},
        "deaths": {"value": 14, "source_span": "14 people have died"},
    },
    "confidence": 0.94,
}


def test_a_well_formed_response_parses_into_an_extraction() -> None:
    extraction = parse_extraction(json.dumps(GROUNDED))

    assert isinstance(extraction, Extraction)
    assert extraction.disease is not None


def test_prose_around_the_json_is_rejected() -> None:
    with pytest.raises(Rejected) as error:
        parse_extraction("Here you go:\n" + json.dumps(GROUNDED))

    assert error.value.reason is RejectionReason.NOT_JSON


def test_a_fenced_code_block_is_rejected() -> None:
    with pytest.raises(Rejected) as error:
        parse_extraction("```json\n" + json.dumps(GROUNDED) + "\n```")

    assert error.value.reason is RejectionReason.NOT_JSON


def test_an_extra_key_is_rejected_as_a_shape_failure() -> None:
    payload = dict(GROUNDED, create_or_update_event=True)

    with pytest.raises(Rejected) as error:
        parse_extraction(json.dumps(payload))

    assert error.value.reason is RejectionReason.SHAPE


def test_deaths_above_total_cases_are_rejected() -> None:
    payload = json.loads(json.dumps(GROUNDED))
    payload["epidemiology"]["deaths"] = {"value": 900, "source_span": "900 died"}

    with pytest.raises(Rejected) as error:
        parse_extraction(json.dumps(payload))

    assert error.value.reason is RejectionReason.ARITHMETIC


def test_confirmed_and_suspected_above_total_are_rejected() -> None:
    payload = json.loads(json.dumps(GROUNDED))
    payload["epidemiology"]["suspected_cases"] = {
        "value": 200,
        "source_span": "200 suspected cases",
    }

    with pytest.raises(Rejected) as error:
        parse_extraction(json.dumps(payload))

    assert error.value.reason is RejectionReason.ARITHMETIC


def test_new_deaths_above_deaths_are_rejected() -> None:
    payload = json.loads(json.dumps(GROUNDED))
    payload["epidemiology"]["new_deaths"] = {"value": 20, "source_span": "20 new deaths"}

    with pytest.raises(Rejected) as error:
        parse_extraction(json.dumps(payload))

    assert error.value.reason is RejectionReason.ARITHMETIC


def test_a_comparison_with_a_missing_side_is_not_a_contradiction() -> None:
    payload = json.loads(json.dumps(GROUNDED))
    del payload["epidemiology"]["total_cases"]

    extraction = parse_extraction(json.dumps(payload))

    assert extraction.epidemiology.total_cases is None
