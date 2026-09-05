"""Strict parsing for active relevance and identity-extraction answers."""

import json
from collections.abc import Sequence
from enum import StrEnum

from pydantic import ValidationError

from episignal_backend.ai.schema import ClassificationVerdict, Epidemiology, Extraction


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
    def __init__(self, reason: RejectionReason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


MIN_CONFIDENCE_DEFAULT = 0.60
_ACTIVE_EXTRACTION_KEYS = frozenset({"disease", "locations"})


def _loads(content: str) -> object:
    try:
        return json.loads(content)
    except json.JSONDecodeError as error:
        raise Rejected(RejectionReason.NOT_JSON, str(error)) from error


def parse_extraction(content: str) -> Extraction:
    try:
        return Extraction.model_validate(_loads(content))
    except ValidationError as error:
        raise Rejected(RejectionReason.SHAPE, error.title) from error


def validate_extraction(
    content: str,
    raw_text: str | Sequence[str] = "",
    *,
    title: str | Sequence[str] | None = None,
    min_confidence: float = 0.0,
) -> Extraction:
    """Validate only the exact identity schema.

    Extra arguments remain for source compatibility with old callers. Active
    extraction contains no confidence, counts, spans, or prose claims.
    """
    del raw_text, title, min_confidence
    payload = _loads(content)
    if not isinstance(payload, dict) or set(payload) != _ACTIVE_EXTRACTION_KEYS:
        raise Rejected(RejectionReason.SHAPE, "extraction must contain only disease and locations")
    return parse_extraction(content)


def validate_classification(content: str) -> ClassificationVerdict:
    try:
        return ClassificationVerdict.model_validate(_loads(content))
    except ValidationError as error:
        raise Rejected(RejectionReason.SHAPE, error.title) from error


# Historical benchmark helpers remain importable but do no active work because
# current extraction contains none of their former fields.
def check_arithmetic(epidemiology: Epidemiology) -> None:
    del epidemiology


def check_grounding(extraction: Extraction, bodies: Sequence[str]) -> None:
    del extraction, bodies


def check_privacy(extraction: Extraction) -> None:
    del extraction
