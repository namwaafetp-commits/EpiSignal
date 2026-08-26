"""Contracts passed between a connector and the pipeline.

`RawDocument` is whatever the source returned, untouched, so a normalization bug
can be reproduced from the stored payload. `NormalizedSignal` is the subset of
`signals` a connector is allowed to populate: fields owned by later slices, such
as `summary` and the AI columns, are absent rather than defaulted, because a
placeholder in an evidence column would be a fabricated value.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from episignal_backend.db.types import ProcessingStatus, SignalType


class RawDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    payload: dict[str, Any]
    retrieved_at: datetime


class NormalizedSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    external_id: str | None = None
    url: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    raw_text: str
    published_at: datetime
    retrieved_at: datetime
    language: str = "en"
    content_hash: str = Field(min_length=64, max_length=64)
    signal_type: SignalType = SignalType.UNKNOWN
    processing_status: ProcessingStatus = ProcessingStatus.FETCHED

    @field_validator("title")
    @classmethod
    def title_is_not_blank(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("title must not be blank")
        return collapsed

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def timestamp_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must carry a timezone")
        return value
