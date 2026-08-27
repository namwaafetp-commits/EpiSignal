"""Contracts passed between a connector and the pipeline.

`RawDocument` is whatever the source returned, untouched, so a normalization bug
can be reproduced from the stored payload. `NormalizedSignal` is the subset of
`signals` a connector is allowed to populate: fields owned by later slices, such
as `summary` and the AI columns, are absent rather than defaulted, because a
placeholder in an evidence column would be a fabricated value.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from episignal_backend.db.types import ProcessingStatus, SignalType


def _require_aware(value: datetime) -> datetime:
    # Reject naive timestamps at the boundary: the columns are timestamptz, and a
    # naive value would otherwise fail far from where it entered. The source's
    # own offset is preserved rather than converted to UTC.
    if value.tzinfo is None:
        raise ValueError("timestamps must carry a timezone")
    return value


class RawDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    payload: dict[str, Any]
    retrieved_at: datetime
    source_url: str | None = None

    @field_validator("retrieved_at")
    @classmethod
    def retrieved_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)


class NormalizedSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    external_id: str | None = None
    url: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    raw_text: str
    published_at: datetime
    retrieved_at: datetime
    language: str = Field(default="en", min_length=2, max_length=8)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    signal_type: SignalType = SignalType.UNKNOWN
    processing_status: ProcessingStatus = ProcessingStatus.FETCHED

    @field_validator("title")
    @classmethod
    def collapse_title(cls, value: str) -> str:
        # Collapsed rather than merely checked: a reflowed title is not a different
        # title, and content_hash collapses identically when fingerprinting.
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("title must not be blank")
        return collapsed

    @field_validator("url", "canonical_url")
    @classmethod
    def url_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("url must not be blank")
        return value

    @field_validator("raw_text")
    @classmethod
    def raw_text_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("raw_text must not be blank")
        return value

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)


class QueryRule(BaseModel):
    """One stored GDELT query, grouped by the kind of signal it looks for."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID | None = None
    rule_group: str = Field(min_length=1)
    query: str = Field(min_length=1)
    label: str = Field(min_length=1)
    language: str = "any"


class TimeWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @model_validator(mode="after")
    def end_is_not_before_start(self) -> "TimeWindow":
        if self.end < self.start:
            raise ValueError("window end must not precede its start")
        return self


class Publisher(BaseModel):
    """The outlet that wrote the article, which is the source of record.

    GDELT discovered it; GDELT did not publish it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    domain: str = Field(min_length=1)
    name: str = Field(min_length=1)
    language: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        collapsed = value.strip().lower()
        if not collapsed:
            raise ValueError("domain must not be blank")
        return collapsed

    @field_validator("name")
    @classmethod
    def collapse_name(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("name must not be blank")
        return collapsed


class DiscoveredArticle(BaseModel):
    """What GDELT returned: metadata only, no publication time, no body text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    gdelt_seen_at: datetime
    language: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    query_rule_id: UUID | None = None

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        collapsed = value.strip().lower()
        if not collapsed:
            raise ValueError("domain must not be blank")
        return collapsed

    @field_validator("gdelt_seen_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)


class DiscoveredSignal(BaseModel):
    """A discovered article ready to store.

    `raw_text` and `published_at` are optional because a page can fail to yield
    either. A stub with neither is stored as `needs_review` rather than dropped:
    the discovery is itself evidence, and a user can still open the original URL.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    raw_text: str | None = None
    published_at: datetime | None = None
    published_at_offset_minutes: int | None = None
    retrieved_at: datetime
    first_seen_at: datetime
    gdelt_seen_at: datetime
    language: str | None = Field(default=None, max_length=8)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    publisher: Publisher
    query_rule_id: UUID | None = None
    processing_status: ProcessingStatus = ProcessingStatus.FETCHED

    @field_validator("title")
    @classmethod
    def collapse_title(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("title must not be blank")
        return collapsed

    @field_validator("raw_text")
    @classmethod
    def raw_text_is_absent_or_meaningful(cls, value: str | None) -> str | None:
        # A blank string would read as stored evidence that says nothing, which
        # is worse than an explicit absence.
        if value is not None and not value.strip():
            raise ValueError("raw_text must be absent rather than blank")
        return value

    @field_validator("retrieved_at", "first_seen_at", "gdelt_seen_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)

    @field_validator("published_at")
    @classmethod
    def published_at_is_aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_aware(value)


class StubRetrieval(BaseModel):
    """A stored stub waiting for another attempt at its page.

    Carries the article as GDELT reported it, so the retry pass can call the
    same `retrieve` the discovery pass uses, and the original `first_seen_at`,
    which a retry must never reset.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: UUID
    article: DiscoveredArticle
    first_seen_at: datetime
    attempts: int = Field(ge=0)

    @field_validator("first_seen_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)
