"""The contract with the model, and the shape stored in `signals.ai_extraction`.

Strict on purpose. A model that returns an extra key has not understood the
question, and a key nobody validates is a value nobody can trust. `extra` is
forbidden everywhere, and every number carries the span of the article that
supports it, because a bare number cannot be checked against anything.

This module imports neither SQLAlchemy nor httpx.
"""

import re
from datetime import date
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from episignal_backend.db.types import LocationRole, SignalType

SPAN_MAX_CHARACTERS = 300
BRIEF_POINT_MAX_CHARACTERS = 200
TITLE_MAX_CHARACTERS = 300


def _require_span(value: str) -> str:
    collapsed = " ".join(value.split())
    if not collapsed:
        raise ValueError("source_span must quote the article, not be blank")
    return collapsed


class BriefSlot(StrEnum):
    """One of the five questions a brief answers, in the order it is asked."""

    WHAT_WHERE = "what_where"
    COUNTS = "counts"
    TIMING = "timing"
    SPREAD = "spread"
    REPORTING = "reporting"


# Declaration order is the required order of a brief, so the enum is the
# authority on both which slots exist and what sequence they come in.
BRIEF_SLOTS: tuple[BriefSlot, ...] = tuple(BriefSlot)
BRIEF_SLOT_COUNT = len(BRIEF_SLOTS)


class BriefPoint(BaseModel):
    """One bullet of a brief.

    `reported` is false when the article never addressed this slot. The text
    still has to say something — it says what is missing — because an empty
    bullet and an unreported fact would look identical to a reader.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot: BriefSlot
    text: str = Field(min_length=1, max_length=BRIEF_POINT_MAX_CHARACTERS)
    reported: bool

    @field_validator("text")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("a brief point must say something, including an absence")
        return collapsed


class GroundedCount(BaseModel):
    """A count, together with the words of the article that state it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: int = Field(ge=0)
    source_span: str = Field(max_length=SPAN_MAX_CHARACTERS)

    @field_validator("source_span")
    @classmethod
    def span_is_not_blank(cls, value: str) -> str:
        return _require_span(value)


class GroundedFlag(BaseModel):
    """A yes or no the article actually makes, with the words that make it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: bool
    source_span: str = Field(max_length=SPAN_MAX_CHARACTERS)

    @field_validator("source_span")
    @classmethod
    def span_is_not_blank(cls, value: str) -> str:
        return _require_span(value)


class NamedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: LocationRole
    country: str | None = Field(default=None, max_length=100)
    admin1: str | None = Field(default=None, max_length=200)
    place_name: str | None = Field(default=None, max_length=200)


class Epidemiology(BaseModel):
    """Counts. Every one is absent or grounded; none is ever inferred."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    suspected_cases: GroundedCount | None = None
    confirmed_cases: GroundedCount | None = None
    total_cases: GroundedCount | None = None
    deaths: GroundedCount | None = None
    new_cases: GroundedCount | None = None
    new_deaths: GroundedCount | None = None


class ExtractedDates(BaseModel):
    """Only dates the prose states.

    `published_at` is deliberately absent: it is read from the page itself
    during discovery, and asking a model to restate a fact already known invites
    it to disagree with one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    data_as_of: date | None = None
    event_date: date | None = None


class Transmission(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    local_transmission: GroundedFlag | None = None
    imported: GroundedFlag | None = None

    def is_empty(self) -> bool:
        return self.local_transmission is None and self.imported is None


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_type: SignalType
    source_language: str | None = None
    title_english: str = Field(min_length=1, max_length=TITLE_MAX_CHARACTERS)
    brief: tuple[BriefPoint, ...]
    disease: NamedEntity | None = None
    pathogen: NamedEntity | None = None
    locations: tuple[ExtractedLocation, ...] = ()
    epidemiology: Epidemiology = Epidemiology()
    dates: ExtractedDates = ExtractedDates()
    transmission: Transmission | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("source_language")
    @classmethod
    def language_is_a_code(cls, value: str | None) -> str | None:
        # Null means the model was unsure, which is recorded rather than guessed.
        if value is None:
            return None
        code = value.strip().lower()
        if not re.fullmatch(r"[a-z]{2}", code):
            raise ValueError("source_language must be an ISO 639-1 two-letter code or null")
        return code

    @field_validator("title_english")
    @classmethod
    def collapse_title(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("title_english must not be blank")
        return collapsed

    @field_validator("brief")
    @classmethod
    def brief_fills_every_slot_in_order(
        cls, value: tuple[BriefPoint, ...]
    ) -> tuple[BriefPoint, ...]:
        # Rejected, never re-ordered. A model that returned the slots in its own
        # order did not follow the contract, and quietly sorting its answer
        # teaches the next reader that the order was never load-bearing.
        if tuple(point.slot for point in value) != BRIEF_SLOTS:
            raise ValueError("brief must carry exactly one point per slot, in slot order")
        return value


def extraction_json_schema() -> dict[str, Any]:
    """The schema the prompt carries, generated from the model it validates.

    One source of truth: a prompt that describes a different shape from the
    validator is a prompt that produces rejections nobody can explain.
    """
    return Extraction.model_json_schema()


class ClassificationVerdict(BaseModel):
    """One signal's relevance decision, addressed by the id it was sent with."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    is_public_health_relevant: bool
    signal_type: SignalType
    relevance: float = Field(ge=0.0, le=1.0)


class ClassificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # min_length=1: an empty result set is not an answer about zero signals, it
    # is a model that did not answer, and it must escalate rather than silently
    # clear a batch.
    results: tuple[ClassificationVerdict, ...] = Field(min_length=1)


def classification_json_schema() -> dict[str, Any]:
    return ClassificationResponse.model_json_schema()
