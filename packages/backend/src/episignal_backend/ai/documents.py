"""Contracts crossing the model seam and the storage seam.

`ChatRequest` and `ChatResponse` describe one HTTP round trip and know nothing
about price: pricing belongs to the ladder, and a transport that knew prices
would change every time one moved. `AiRequestRecord` is the cost row, and it
carries the price that was in force at the moment of the call, because a price
is a fact about a moment.

This module imports neither SQLAlchemy nor httpx.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from episignal_backend.ai.schema import Extraction
from episignal_backend.db.types import AiOutcome, AiProvider, AiPurpose, SignalType

LOWEST_TIER = 1
HIGHEST_TIER = 3


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must carry a timezone")
    return value


def _require_text(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


class ModelSpec(BaseModel):
    """One rung of the ladder, as the roster stores it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    tier: int = Field(ge=LOWEST_TIER, le=HIGHEST_TIER)
    model_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    provider: AiProvider = AiProvider.OPENROUTER
    prompt_price_per_million: Decimal = Field(ge=0)
    completion_price_per_million: Decimal = Field(ge=0)


class ClassifiableSignal(BaseModel):
    """A stored signal awaiting a relevance decision.

    Carries an excerpt rather than the body: relevance is decided from the title
    and the opening, and sending whole articles for a decision this cheap would
    spend the batch's whole input budget on one of them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    title: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)

    @field_validator("title", "excerpt")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        return _require_text(value)


class ExtractableSignal(BaseModel):
    """A signal judged relevant, with the text its extraction must be grounded in."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    title: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)

    @field_validator("title", "raw_text")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        return _require_text(value)


class Verdict(BaseModel):
    """The relevance decision written back to one signal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_public_health_relevant: bool
    signal_type: SignalType
    relevance: float = Field(ge=0.0, le=1.0)
    model_id: str = Field(min_length=1)
    decided_at: datetime

    @field_validator("decided_at")
    @classmethod
    def decided_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)


class StoredExtraction(BaseModel):
    """An accepted extraction, with the disease it resolved to if any."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    extraction: Extraction
    disease_id: UUID | None = None
    model_id: str = Field(min_length=1)
    processed_at: datetime

    @field_validator("processed_at")
    @classmethod
    def processed_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)


@dataclass(frozen=True)
class DiseaseCandidate:
    """One row of the reviewed disease vocabulary, as the classifier sees it.

    A dataclass rather than a model: the vocabulary is written by reviewers,
    never parsed from an answer.
    """

    slug: str
    canonical_name: str
    synonyms: Sequence[str] = ()


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    system: str = Field(min_length=1)
    user: str = Field(min_length=1)
    response_schema: dict[str, Any] | None = None
    schema_name: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    usage: TokenUsage = TokenUsage()
    http_status: int | None = None
    latency_ms: int = Field(ge=0)


class AiRequestRecord(BaseModel):
    """The cost row. Written for every request, answered or not."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ai_model_id: UUID | None
    model_id: str = Field(min_length=1)
    tier: int = Field(ge=LOWEST_TIER, le=HIGHEST_TIER)
    purpose: AiPurpose
    signal_id: UUID | None
    batch_size: int = Field(ge=1)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    latency_ms: int = Field(ge=0)
    http_status: int | None = None
    outcome: AiOutcome
    rejection_reason: str | None = None
    prompt_price_per_million: Decimal = Field(ge=0)
    completion_price_per_million: Decimal = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)
    requested_at: datetime

    @field_validator("requested_at")
    @classmethod
    def requested_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value)
