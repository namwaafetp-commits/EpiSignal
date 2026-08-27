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


from pathlib import Path

from episignal_backend.ai.validate import MIN_CONFIDENCE_DEFAULT, validate_extraction

FIXTURES = Path(__file__).parent / "fixtures"
BODY = (FIXTURES / "ai_outbreak_body.txt").read_text(encoding="utf-8")


def grounded_payload() -> dict[str, object]:
    return {
        "signal_type": "outbreak_report",
        "summary": "Cholera outbreak reported in Luanda province.",
        "disease": {"name": "Cholera", "confidence": 0.97},
        "locations": [{"role": "primary", "country": "Angola", "place_name": "Luanda"}],
        "epidemiology": {
            "confirmed_cases": {"value": 327, "source_span": "327 confirmed cases"},
            "total_cases": {"value": 400, "source_span": "400 cases in total"},
            "deaths": {"value": 14, "source_span": "14 people have died"},
        },
        "dates": {"data_as_of": "2026-08-25"},
        "transmission": {
            "local_transmission": {
                "value": True,
                "source_span": "all cases were acquired locally",
            }
        },
        "confidence": 0.94,
    }


def test_an_extraction_whose_spans_are_in_the_article_is_accepted() -> None:
    extraction = validate_extraction(json.dumps(grounded_payload()), BODY)

    assert extraction.epidemiology.deaths is not None
    assert extraction.epidemiology.deaths.value == 14


def test_a_span_the_article_does_not_contain_is_rejected() -> None:
    content = (FIXTURES / "ai_ungrounded_response.json").read_text(encoding="utf-8")

    with pytest.raises(Rejected) as error:
        validate_extraction(content, BODY)

    assert error.value.reason is RejectionReason.UNGROUNDED


def test_a_span_that_does_not_contain_its_own_number_is_rejected() -> None:
    payload = grounded_payload()
    payload["epidemiology"] = {
        "deaths": {"value": 14, "source_span": "Officials said"}
    }

    with pytest.raises(Rejected) as error:
        validate_extraction(json.dumps(payload), BODY)

    assert error.value.reason is RejectionReason.UNGROUNDED


def test_a_span_is_matched_across_a_line_break_in_the_article() -> None:
    payload = grounded_payload()
    payload["epidemiology"] = {
        "confirmed_cases": {"value": 327, "source_span": "327 confirmed cases recorded"}
    }

    extraction = validate_extraction(json.dumps(payload), BODY)

    assert extraction.epidemiology.confirmed_cases is not None


def test_a_transmission_object_with_no_flags_is_stored_as_absent() -> None:
    payload = grounded_payload()
    payload["transmission"] = {}

    extraction = validate_extraction(json.dumps(payload), BODY)

    assert extraction.transmission is None


def test_an_ungrounded_transmission_flag_is_rejected() -> None:
    payload = grounded_payload()
    payload["transmission"] = {
        "imported": {"value": True, "source_span": "the case was imported from Namibia"}
    }

    with pytest.raises(Rejected) as error:
        validate_extraction(json.dumps(payload), BODY)

    assert error.value.reason is RejectionReason.UNGROUNDED


def test_a_summary_carrying_a_telephone_number_is_rejected() -> None:
    payload = grounded_payload()
    payload["summary"] = "Call the family on +244 923 555 0142 for details."

    with pytest.raises(Rejected) as error:
        validate_extraction(json.dumps(payload), BODY)

    assert error.value.reason is RejectionReason.PRIVACY


def test_a_place_name_carrying_an_email_address_is_rejected() -> None:
    payload = grounded_payload()
    payload["locations"] = [
        {"role": "primary", "country": "Angola", "place_name": "contact@example.com"}
    ]

    with pytest.raises(Rejected) as error:
        validate_extraction(json.dumps(payload), BODY)

    assert error.value.reason is RejectionReason.PRIVACY


def test_confidence_below_the_floor_is_rejected() -> None:
    payload = grounded_payload()
    payload["confidence"] = 0.2

    with pytest.raises(Rejected) as error:
        validate_extraction(json.dumps(payload), BODY, min_confidence=MIN_CONFIDENCE_DEFAULT)

    assert error.value.reason is RejectionReason.LOW_CONFIDENCE


def test_grounding_is_checked_before_confidence() -> None:
    payload = grounded_payload()
    payload["confidence"] = 0.1
    payload["epidemiology"] = {"deaths": {"value": 99, "source_span": "99 people have died"}}

    with pytest.raises(Rejected) as error:
        validate_extraction(json.dumps(payload), BODY)

    assert error.value.reason is RejectionReason.UNGROUNDED

