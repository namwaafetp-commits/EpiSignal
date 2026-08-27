"""Reviewed canonical identities loaded from `database/seeds`.

Seeding is idempotent: diseases match on `slug` and sources match on `name`, so
re-running never duplicates an identity and never rewrites generated keys or
creation timestamps.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from episignal_backend.db.types import CredibilityTier, SourceType
from episignal_backend.models import Disease, GdeltQueryRule, Source
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


@dataclass(frozen=True)
class SeedResult:
    diseases: int
    sources: int
    query_rules: int


def _read_seed(name: str) -> object:
    path = Path(__file__).parents[4] / "database" / "seeds" / name
    return json.loads(path.read_text(encoding="utf-8"))


def load_diseases() -> tuple[DiseaseSeed, ...]:
    return tuple(TypeAdapter(list[DiseaseSeed]).validate_python(_read_seed("diseases.json")))


def load_sources() -> tuple[SourceSeed, ...]:
    return tuple(TypeAdapter(list[SourceSeed]).validate_python(_read_seed("sources.json")))


def load_query_rules() -> tuple[QueryRuleSeed, ...]:
    return tuple(
        TypeAdapter(list[QueryRuleSeed]).validate_python(_read_seed("gdelt_queries.json"))
    )


def _upsert(
    session: Session,
    model: type[Disease] | type[Source] | type[GdeltQueryRule],
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
    _upsert(session, Disease, [item.model_dump() for item in diseases], ("slug",))
    _upsert(session, Source, [item.model_dump() for item in sources], ("name",))
    _upsert(
        session,
        GdeltQueryRule,
        [item.model_dump() for item in query_rules],
        ("query", "language"),
    )
    return SeedResult(
        diseases=len(diseases), sources=len(sources), query_rules=len(query_rules)
    )
