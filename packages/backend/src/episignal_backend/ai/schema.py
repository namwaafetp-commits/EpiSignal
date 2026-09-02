"""The contract with the model, and the shape stored in `signals.ai_extraction`.

Strict on purpose. A model that returns an extra key has not understood the
question, and a key nobody validates is a value nobody can trust. `extra` is
forbidden everywhere, and every number carries the span of the article that
supports it, because a bare number cannot be checked against anything.

This module imports neither SQLAlchemy nor httpx.
"""

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from episignal_backend.db.types import LocationRole, SignalType

# Bumped when the shape of a stored extraction changes. Version 1 is every row
# written before the brief existed: it has a `summary` and no `brief`.
EXTRACTION_SCHEMA_VERSION = 5
BACKFILL_MIN_SCHEMA_VERSION = 2
EXTRACTION_VERSION_KEY = "extraction_schema_version"

SPAN_MAX_CHARACTERS = 300
BRIEF_POINT_MAX_CHARACTERS = 200
TITLE_MAX_CHARACTERS = 300

ISO_639_1_CODES: frozenset[str] = frozenset(
    [
        "aa",
        "ab",
        "ae",
        "af",
        "ak",
        "am",
        "an",
        "ar",
        "as",
        "av",
        "ay",
        "az",
        "ba",
        "be",
        "bg",
        "bh",
        "bi",
        "bm",
        "bn",
        "bo",
        "br",
        "bs",
        "ca",
        "ce",
        "ch",
        "co",
        "cr",
        "cs",
        "cu",
        "cv",
        "cy",
        "da",
        "de",
        "dv",
        "dz",
        "ee",
        "el",
        "en",
        "eo",
        "es",
        "et",
        "eu",
        "fa",
        "ff",
        "fi",
        "fj",
        "fo",
        "fr",
        "fy",
        "ga",
        "gd",
        "gl",
        "gn",
        "gu",
        "gv",
        "ha",
        "he",
        "hi",
        "ho",
        "hr",
        "ht",
        "hu",
        "hy",
        "hz",
        "ia",
        "id",
        "ie",
        "ig",
        "ii",
        "ik",
        "io",
        "is",
        "it",
        "iu",
        "ja",
        "jv",
        "ka",
        "kg",
        "ki",
        "kj",
        "kk",
        "kl",
        "km",
        "kn",
        "ko",
        "kr",
        "ks",
        "ku",
        "kv",
        "kw",
        "ky",
        "la",
        "lb",
        "lg",
        "li",
        "ln",
        "lo",
        "lt",
        "lu",
        "lv",
        "mg",
        "mh",
        "mi",
        "mk",
        "ml",
        "mn",
        "mr",
        "ms",
        "mt",
        "my",
        "na",
        "nb",
        "nd",
        "ne",
        "ng",
        "nl",
        "nn",
        "no",
        "nr",
        "nv",
        "ny",
        "oc",
        "oj",
        "om",
        "or",
        "os",
        "pa",
        "pi",
        "pl",
        "ps",
        "pt",
        "qu",
        "rm",
        "rn",
        "ro",
        "ru",
        "rw",
        "sa",
        "sc",
        "sd",
        "se",
        "sg",
        "si",
        "sk",
        "sl",
        "sm",
        "sn",
        "so",
        "sq",
        "sr",
        "ss",
        "st",
        "su",
        "sv",
        "sw",
        "ta",
        "te",
        "tg",
        "th",
        "ti",
        "tk",
        "tl",
        "tn",
        "to",
        "tr",
        "ts",
        "tt",
        "tw",
        "ty",
        "ug",
        "uk",
        "ur",
        "uz",
        "ve",
        "vi",
        "vo",
        "wa",
        "wo",
        "xh",
        "yi",
        "yo",
        "za",
        "zh",
        "zu",
    ]
)


def _require_span(value: str) -> str:
    collapsed = " ".join(value.split())
    if not collapsed:
        raise ValueError("source_span must quote the article, not be blank")
    return collapsed


class TriageCategory(StrEnum):
    INFECTIOUS_DISEASE = "infectious_disease"
    ENVIRONMENTAL = "environmental"
    CHEMICAL = "chemical"
    OTHER_PUBLIC_HEALTH = "other_public_health"
    NOT_PUBLIC_HEALTH = "not_public_health"


class TriageVerdict(BaseModel):
    """Cheap metadata from a headline and opening paragraph.

    Facts stay nullable because forcing a small model to fill them invites
    invention. The two judgements and their confidence are always required.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    relevant: bool
    public_health: bool
    category: TriageCategory | None = None
    event_type: SignalType | None = None
    disease: str | None = Field(default=None, max_length=200)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    admin1: str | None = Field(default=None, max_length=200)
    admin2: str | None = Field(default=None, max_length=200)
    location_text: str | None = Field(default=None, max_length=300)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("disease", "admin1", "admin2", "location_text", mode="before")
    @classmethod
    def blank_is_missing(cls, value: object) -> object:
        if isinstance(value, str) and (
            not value.strip() or value.strip().lower() in {"unknown", "n/a", "none"}
        ):
            return None
        return value

    @field_validator("country", mode="before")
    @classmethod
    def country_is_upper(cls, value: object) -> object:
        if isinstance(value, str):
            collapsed = value.strip().upper()
            return collapsed or None
        return value


def triage_json_schema() -> dict[str, Any]:
    return TriageVerdict.model_json_schema()


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
    source_index: int = Field(default=0, ge=0)

    @field_validator("source_span")
    @classmethod
    def span_is_not_blank(cls, value: str) -> str:
        return _require_span(value)


class GroundedFlag(BaseModel):
    """A yes or no the article actually makes, with the words that make it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: bool
    source_span: str = Field(max_length=SPAN_MAX_CHARACTERS)
    source_index: int = Field(default=0, ge=0)

    @field_validator("source_span")
    @classmethod
    def span_is_not_blank(cls, value: str) -> str:
        return _require_span(value)


class GroundedEvidence(BaseModel):
    """One evidence primitive, with the exact source that supports it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1, max_length=SPAN_MAX_CHARACTERS)
    source_span: str = Field(max_length=SPAN_MAX_CHARACTERS)
    source_index: int = Field(default=0, ge=0)

    @field_validator("text", "source_span")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        return _require_span(value)


class NamedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)


class DiseaseIdentity(str):
    """String disease identity with read-only legacy ``name`` compatibility."""

    @property
    def name(self) -> str:
        return str(self)

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        from pydantic_core import core_schema

        return core_schema.no_info_after_validator_function(cls, core_schema.str_schema())


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


class ExtractionLocation(BaseModel):
    """One event location exactly as the extraction model reports it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    town: str | None = Field(max_length=200)
    country: str | None = Field(max_length=100)

    @field_validator("town", "country", mode="before")
    @classmethod
    def collapse_optional_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        collapsed = " ".join(value.split())
        return collapsed or None


class Extraction(BaseModel):
    """The complete active model contract: event identity only."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    disease: DiseaseIdentity | None = Field(default=None, max_length=200)
    # Deprecated fields remain readable for historical benchmark rows. The
    # active wire parser below rejects them and storage omits them.
    signal_type: SignalType = SignalType.UNKNOWN
    source_language: str | None = None
    title_english: str | None = None
    brief: tuple[BriefPoint, ...] = ()
    pathogen: NamedEntity | None = None
    epidemiology: Epidemiology = Epidemiology()
    dates: ExtractedDates = ExtractedDates()
    transmission: Transmission | None = None
    response_actions: tuple[GroundedEvidence, ...] = ()
    driver_or_barrier_evidence: tuple[GroundedEvidence, ...] = ()
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    locations: tuple[ExtractionLocation, ...] = ()

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Expose only the active identity contract on model-facing schemas."""
        if cls is Extraction:
            return extraction_json_schema()
        return super().model_json_schema(*args, **kwargs)

    @field_validator("disease", mode="before")
    @classmethod
    def collapse_disease(cls, value: object) -> object:
        if isinstance(value, dict):
            value = value.get("name")
        if not isinstance(value, str):
            return value
        collapsed = " ".join(value.split())
        return DiseaseIdentity(collapsed) if collapsed else None

    @field_validator("locations")
    @classmethod
    def remove_exact_duplicates(
        cls, value: tuple[ExtractionLocation, ...]
    ) -> tuple[ExtractionLocation, ...]:
        seen: set[tuple[str | None, str | None]] = set()
        unique: list[ExtractionLocation] = []
        for location in value:
            key = (
                location.town.casefold() if location.town else None,
                location.country.casefold() if location.country else None,
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(location)
        return tuple(unique)


class StoredExtractionPayload(Extraction):
    """Read both current identity-only rows and historical extraction rows."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    @model_validator(mode="before")
    @classmethod
    def translate_historical_shape(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        disease = payload.get("disease_text", payload.get("disease"))
        if isinstance(disease, dict):
            disease = disease.get("name")
        locations: list[dict[str, object]] = []
        raw_locations = payload.get("locations")
        if isinstance(raw_locations, (list, tuple)):
            for raw in raw_locations:
                if not isinstance(raw, dict):
                    continue
                town = raw.get("town")
                if town is None:
                    town = raw.get("place_name") or raw.get("admin2") or raw.get("admin1")
                locations.append(
                    {
                        "town": town,
                        "country": raw.get("country")
                        or raw.get("country_code")
                        or raw.get("country_name"),
                    }
                )
        return {"disease": disease, "locations": locations}


def extraction_json_schema() -> dict[str, Any]:
    """The schema the prompt carries, generated from the model it validates.

    One source of truth: a prompt that describes a different shape from the
    validator is a prompt that produces rejections nobody can explain.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["disease", "locations"],
        "properties": {
            "disease": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "locations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["town", "country"],
                    "properties": {
                        "town": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "country": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    },
                },
            },
        },
    }


class ClassificationVerdict(BaseModel):
    """One signal's relevance decision from discovery metadata only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relevant: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason_code: str | None = Field(default=None, min_length=1, max_length=64)


class ClassificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # min_length=1: an empty result set is not an answer about zero signals, it
    # is a model that did not answer, and it must escalate rather than silently
    # clear a batch.
    results: tuple[ClassificationVerdict, ...] = Field(min_length=1)


def classification_json_schema() -> dict[str, Any]:
    return ClassificationVerdict.model_json_schema()
