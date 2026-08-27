"""Reviewed canonical identities loaded from `database/seeds`.

Seeding is idempotent: diseases match on `slug` and sources match on `name`, so
re-running never duplicates an identity and never rewrites generated keys or
creation timestamps.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from episignal_backend.db.types import CredibilityTier, FilterRuleGroup, SourceType
from episignal_backend.models import (
    AiModel,
    Disease,
    GdeltQueryRule,
    SignalFilterRule,
    Source,
)
from episignal_backend.models.discovery import ANY_LANGUAGE


class DiseaseSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_name: str = Field(min_length=1)
    slug: str = Field(min_length=1, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    icd10: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    category: str | None = None


class SourceSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    source_type: SourceType
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    base_url: str = Field(pattern=r"^https://")
    feed_url: str | None = Field(default=None, pattern=r"^https://")
    credibility_tier: CredibilityTier
    is_official: bool
    language: str = "en"
    active: bool = False


class QueryRuleSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_group: str = Field(min_length=1)
    query: str = Field(min_length=1)
    label: str = Field(min_length=1)
    language: str = ANY_LANGUAGE
    active: bool = True


class FilterRuleSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_group: FilterRuleGroup
    pattern: str = Field(min_length=1)
    label: str = Field(min_length=1)
    active: bool = True


class AiModelSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tier: int = Field(ge=1, le=3)
    model_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    # Strings in the JSON, parsed as Decimal: a price written as a float would
    # be stored as the nearest binary approximation of itself.
    prompt_price_per_million: Decimal = Field(ge=0)
    completion_price_per_million: Decimal = Field(ge=0)
    active: bool = True


class CountryAliasSeed(BaseModel):
    """One accepted spelling of a country, already in normalized form.

    Normalization happens here rather than at lookup time so that a reviewer
    reading the file sees exactly the key the resolver will look up.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    country_code: str = Field(min_length=2, max_length=2, pattern=r"^[A-Z]{2}$")


@dataclass(frozen=True)
class SeedResult:
    diseases: int
    sources: int
    query_rules: int
    filter_rules: int
    ai_models: int


def _read_seed(name: str) -> object:
    path = Path(__file__).parents[4] / "database" / "seeds" / name
    return json.loads(path.read_text(encoding="utf-8"))


def load_diseases() -> tuple[DiseaseSeed, ...]:
    return tuple(TypeAdapter(list[DiseaseSeed]).validate_python(_read_seed("diseases.json")))


def load_sources() -> tuple[SourceSeed, ...]:
    return tuple(TypeAdapter(list[SourceSeed]).validate_python(_read_seed("sources.json")))


def load_query_rules() -> tuple[QueryRuleSeed, ...]:
    return tuple(TypeAdapter(list[QueryRuleSeed]).validate_python(_read_seed("gdelt_queries.json")))


def load_filter_rules() -> tuple[FilterRuleSeed, ...]:
    return tuple(TypeAdapter(list[FilterRuleSeed]).validate_python(_read_seed("filter_rules.json")))


def load_ai_models() -> tuple[AiModelSeed, ...]:
    return tuple(TypeAdapter(list[AiModelSeed]).validate_python(_read_seed("ai_models.json")))


def load_country_aliases() -> tuple[CountryAliasSeed, ...]:
    return tuple(
        TypeAdapter(list[CountryAliasSeed]).validate_python(_read_seed("country_aliases.json"))
    )


def _upsert(
    session: Session,
    model: type[Any],
    rows: list[dict[str, Any]],
    natural_key: tuple[str, ...],
) -> None:
    statement = insert(model).values(rows)
    updates = {
        column.name: getattr(statement.excluded, column.name)
        for column in model.__table__.columns
        if column.name not in {"id", "created_at", *natural_key}
    }
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[getattr(model, name) for name in natural_key],
            set_=updates,
        )
    )


def seed_database(session: Session) -> SeedResult:
    diseases = load_diseases()
    sources = load_sources()
    query_rules = load_query_rules()
    filter_rules = load_filter_rules()
    ai_models = load_ai_models()
    _upsert(session, Disease, [item.model_dump() for item in diseases], ("slug",))
    _upsert(session, Source, [item.model_dump() for item in sources], ("name",))
    _upsert(
        session,
        GdeltQueryRule,
        [item.model_dump() for item in query_rules],
        ("query", "language"),
    )
    _upsert(
        session,
        SignalFilterRule,
        [item.model_dump() for item in filter_rules],
        ("rule_group", "pattern"),
    )
    _upsert(
        session,
        AiModel,
        [item.model_dump() for item in ai_models],
        ("model_id",),
    )
    return SeedResult(
        diseases=len(diseases),
        sources=len(sources),
        query_rules=len(query_rules),
        filter_rules=len(filter_rules),
        ai_models=len(ai_models),
    )
