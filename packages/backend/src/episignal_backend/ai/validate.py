"""Every deterministic check a model answer must pass before it is stored.

The order matters and is the design's order: parse, shape, batch identity,
arithmetic, grounding, emptiness, privacy, confidence. Confidence is last on
purpose, so that a confident fabrication is caught by grounding long before the
model's opinion of itself is consulted.

This module imports neither SQLAlchemy nor httpx.
"""

import json
import re
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


MIN_CONFIDENCE_DEFAULT = 0.60

# Deliberately narrow. This is a check on what this system agrees to store, not
# a PII detector and not a claim about what the publisher wrote. A false
# positive costs one escalation; a false negative stores a person's contact
# details in an evidence column.
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_TELEPHONE = re.compile(r"(?:\+\d[\d\s().-]{7,}\d)|(?:\b\d[\d\s().-]{8,}\d\b)")
_LONG_DIGIT_RUN = re.compile(r"\d{9,}")


def _flatten(text: str) -> str:
    """Whitespace-collapsed and case-folded, so a reflowed article still matches.

    A span copied out of a page that wraps mid-sentence differs from the stored
    text only in whitespace, and rejecting that would reject the honest case.
    """
    return " ".join(text.split()).casefold()


def check_privacy(extraction: Extraction) -> None:
    candidates = [extraction.summary]
    candidates.extend(
        location.place_name for location in extraction.locations if location.place_name
    )
    for candidate in candidates:
        for pattern in (_EMAIL, _TELEPHONE, _LONG_DIGIT_RUN):
            if pattern.search(candidate):
                raise Rejected(RejectionReason.PRIVACY, pattern.pattern)


def _check_span(span: str, flat_body: str, label: str) -> None:
    if _flatten(span) not in flat_body:
        raise Rejected(RejectionReason.UNGROUNDED, label)


def check_grounding(extraction: Extraction, raw_text: str) -> None:
    flat_body = _flatten(raw_text)

    for label, count in (
        ("suspected_cases", extraction.epidemiology.suspected_cases),
        ("confirmed_cases", extraction.epidemiology.confirmed_cases),
        ("total_cases", extraction.epidemiology.total_cases),
        ("deaths", extraction.epidemiology.deaths),
        ("new_cases", extraction.epidemiology.new_cases),
        ("new_deaths", extraction.epidemiology.new_deaths),
    ):
        if count is None:
            continue
        _check_span(count.source_span, flat_body, label)
        # The span must state this number, not merely sit near it. Without this,
        # any true sentence in the article would support any number at all.
        if str(count.value) not in count.source_span:
            raise Rejected(RejectionReason.UNGROUNDED, f"{label} not stated by its span")

    if extraction.transmission is not None:
        for label, flag in (
            ("local_transmission", extraction.transmission.local_transmission),
            ("imported", extraction.transmission.imported),
        ):
            if flag is not None:
                _check_span(flag.source_span, flat_body, label)


def validate_extraction(
    content: str, raw_text: str, *, min_confidence: float = MIN_CONFIDENCE_DEFAULT
) -> Extraction:
    """Every check, in the design's order. The first failure raises."""
    extraction = parse_extraction(content)

    check_grounding(extraction, raw_text)

    if extraction.transmission is not None and extraction.transmission.is_empty():
        # An object with no flags is not a finding. Stored as absence rather
        # than rejected, because saying nothing about transmission is a normal
        # thing for an article to do.
        extraction = extraction.model_copy(update={"transmission": None})

    check_privacy(extraction)

    if extraction.confidence < min_confidence:
        raise Rejected(RejectionReason.LOW_CONFIDENCE, f"{extraction.confidence}")

    return extraction

