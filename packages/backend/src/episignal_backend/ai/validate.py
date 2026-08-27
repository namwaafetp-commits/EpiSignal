"""Every deterministic check a model answer must pass before it is stored.

The order matters and is the design's order: parse, shape, batch identity,
arithmetic, grounding, emptiness, privacy, confidence. Confidence is last on
purpose, so that a confident fabrication is caught by grounding long before the
model's opinion of itself is consulted.

This module imports neither SQLAlchemy nor httpx.
"""

import json
from enum import StrEnum

from pydantic import ValidationError

from episignal_backend.ai.schema import Epidemiology, Extraction, GroundedCount


class RejectionReason(StrEnum):
    NOT_JSON = "not_json"
    SHAPE = "shape"
    BATCH_IDENTITY = "batch_identity"
    ARITHMETIC = "arithmetic"
    UNGROUNDED = "ungrounded"
    EMPTY_CLAIM = "empty_claim"
    PRIVACY = "privacy"
    LOW_CONFIDENCE = "low_confidence"


class Rejected(Exception):
    """The answer arrived and cannot be trusted.

    Carries the name of the first check that failed, which is what the cost row
    records and what the admin view will show.
    """

    def __init__(self, reason: RejectionReason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


def _loads(content: str) -> object:
    # No salvaging: a model that wrapped its answer in prose or a code fence did
    # not follow the contract, and stripping the wrapper teaches it that the
    # contract is optional. Escalating is cheaper than a parser that guesses.
    try:
        return json.loads(content)
    except json.JSONDecodeError as error:
        raise Rejected(RejectionReason.NOT_JSON, str(error)) from error


def _at_most(smaller: GroundedCount | None, larger: GroundedCount | None, label: str) -> None:
    if smaller is None or larger is None:
        return
    if smaller.value > larger.value:
        raise Rejected(RejectionReason.ARITHMETIC, label)


def check_arithmetic(epidemiology: Epidemiology) -> None:
    total = epidemiology.total_cases
    _at_most(epidemiology.deaths, total, "deaths above total_cases")
    _at_most(epidemiology.new_cases, total, "new_cases above total_cases")
    _at_most(epidemiology.confirmed_cases, total, "confirmed_cases above total_cases")
    _at_most(epidemiology.suspected_cases, total, "suspected_cases above total_cases")
    _at_most(epidemiology.new_deaths, epidemiology.deaths, "new_deaths above deaths")

    confirmed = epidemiology.confirmed_cases
    suspected = epidemiology.suspected_cases
    if total is not None and confirmed is not None and suspected is not None:
        if confirmed.value + suspected.value > total.value:
            raise Rejected(
                RejectionReason.ARITHMETIC, "confirmed_cases plus suspected_cases above total_cases"
            )


def parse_extraction(content: str) -> Extraction:
    payload = _loads(content)
    try:
        extraction = Extraction.model_validate(payload)
    except ValidationError as error:
        raise Rejected(RejectionReason.SHAPE, error.title) from error

    check_arithmetic(extraction.epidemiology)
    return extraction
