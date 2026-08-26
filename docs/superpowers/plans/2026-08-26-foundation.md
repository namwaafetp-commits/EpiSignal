# EpiSignal Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lean Windows-first EpiSignal monorepo with a responsive Next.js shell, a tested FastAPI service, a versioned PostgreSQL/PostGIS schema, and idempotent canonical seeds connected to hosted Supabase.

**Architecture:** pnpm manages the Next.js application and generated TypeScript contracts; uv manages a FastAPI application and reusable Python backend package in one workspace. The browser calls FastAPI, FastAPI calls the backend package, and only the backend receives private Supabase connection strings. Alembic owns database history and live database checks are always explicit.

**Tech Stack:** Node.js 22, pnpm 11, Next.js App Router, React, TypeScript, Tailwind CSS, Vitest, Testing Library, Python 3.12, uv, FastAPI, Pydantic Settings, SQLAlchemy 2, psycopg 3, GeoAlchemy2, Alembic, pytest, Ruff, mypy, PostgreSQL/PostGIS on Supabase.

---

## File Structure

```text
apps/web/                         Next.js application and UI tests
apps/api/                         FastAPI composition, routes, middleware, tests
packages/backend/                 Domain models, database configuration, seeds, tests
packages/contracts/               OpenAPI JSON and generated TypeScript declarations
database/migrations/              Alembic environment and immutable revisions
database/seeds/                   Reviewed JSON seed datasets
docs/architecture/                Setup and architectural notes
scripts/                          PowerShell verification and live database smoke scripts
```

Configuration and framework scaffold files are generated or declarative and are the approved TDD exception. Every behavior-bearing Python or TypeScript module follows red-green-refactor.

### Task 1: Scaffold the polyglot workspace

**Files:**
- Create: `.gitignore`
- Create: `.editorconfig`
- Create: `.python-version`
- Create: `package.json`
- Create: `pnpm-workspace.yaml`
- Create: `pyproject.toml`
- Create: `apps/web/**` via `create-next-app`
- Create: `apps/web/.env.local.example`
- Create: `apps/api/pyproject.toml`
- Create: `apps/api/.env.example`
- Create: `apps/api/src/episignal_api/__init__.py`
- Create: `packages/backend/pyproject.toml`
- Create: `packages/backend/src/episignal_backend/__init__.py`
- Create: `packages/contracts/package.json`

- [x] **Step 1: Generate the empty Next.js application**

Run:

```powershell
pnpm create next-app@16.3.2 apps/web --ts --tailwind --eslint --app --src-dir --import-alias "@/*" --empty --use-pnpm --skip-install --disable-git --no-agents-md --yes
```

Expected: `apps/web` contains an App Router project and no nested `.git` directory.

- [x] **Step 2: Add root workspace configuration**

Create `pnpm-workspace.yaml`:

```yaml
packages:
  - apps/web
  - packages/contracts
```

Create root `package.json`:

```json
{
  "name": "episignal",
  "version": "0.1.0",
  "private": true,
  "packageManager": "pnpm@11.19.0",
  "scripts": {
    "dev": "concurrently -n web,api -c cyan,magenta \"pnpm --filter @episignal/web dev\" \"uv run --package episignal-api python -m episignal_api.run\"",
    "build": "pnpm --filter @episignal/web build",
    "lint": "pnpm lint:web && pnpm lint:python",
    "lint:web": "pnpm --filter @episignal/web lint",
    "lint:python": "uv run ruff check .",
    "format:check": "uv run ruff format --check . && pnpm --filter @episignal/web exec prettier --check .",
    "typecheck": "pnpm typecheck:web && uv run mypy apps/api/src packages/backend/src",
    "typecheck:web": "pnpm --filter @episignal/web typecheck",
    "test": "pnpm test:web && uv run pytest",
    "test:web": "pnpm --filter @episignal/web test",
    "contracts:generate": "uv run --package episignal-api python -m episignal_api.export_openapi && pnpm --filter @episignal/contracts generate",
    "contracts:check": "pnpm contracts:generate && git diff --exit-code -- packages/contracts",
    "db:check": "uv run --package episignal-api python -m episignal_api.database_check",
    "db:migrate": "uv run --package episignal-api alembic -c database/alembic.ini upgrade head",
    "db:rollback": "uv run --package episignal-api alembic -c database/alembic.ini downgrade -1",
    "db:seed": "uv run --package episignal-backend python -m episignal_backend.seed_runner",
    "verify": "pnpm format:check && pnpm lint && pnpm typecheck && pnpm test && pnpm contracts:check && pnpm build"
  },
  "devDependencies": {
    "concurrently": "^9.2.1"
  }
}
```

Create root `pyproject.toml`:

```toml
[project]
name = "episignal-workspace"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[dependency-groups]
dev = [
  "mypy>=1.17,<2",
  "pytest>=8.4,<9",
  "pytest-cov>=6.2,<7",
  "ruff>=0.12,<1",
]

[tool.uv.workspace]
members = ["apps/api", "packages/backend"]

[tool.pytest.ini_options]
testpaths = ["apps/api/tests", "packages/backend/tests"]
addopts = "-q --strict-markers"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
packages = ["episignal_api", "episignal_backend"]
```

- [x] **Step 3: Add Python package manifests**

Create `packages/backend/pyproject.toml`:

```toml
[project]
name = "episignal-backend"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "geoalchemy2>=0.18,<1",
  "pydantic-settings>=2.10,<3",
  "psycopg[binary]>=3.2,<4",
  "sqlalchemy>=2.0,<2.1",
]

[build-system]
requires = ["uv_build>=0.8,<0.13"]
build-backend = "uv_build"
```

Create `apps/api/pyproject.toml`:

```toml
[project]
name = "episignal-api"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "alembic>=1.16,<2",
  "episignal-backend",
  "fastapi>=0.116,<1",
  "httpx>=0.28,<1",
  "uvicorn[standard]>=0.35,<1",
]

[tool.uv.sources]
episignal-backend = { workspace = true }

[build-system]
requires = ["uv_build>=0.8,<0.13"]
build-backend = "uv_build"
```

Create `packages/contracts/package.json`:

```json
{
  "name": "@episignal/contracts",
  "version": "0.1.0",
  "private": true,
  "types": "src/index.d.ts",
  "scripts": {
    "generate": "openapi-typescript openapi.json -o src/index.d.ts"
  },
  "devDependencies": {
    "openapi-typescript": "^7.9.1"
  }
}
```

- [x] **Step 4: Add safe environment templates and ignore rules**

Create `apps/api/.env.example`:

```dotenv
EPISIGNAL_ENV=development
EPISIGNAL_API_HOST=127.0.0.1
EPISIGNAL_API_PORT=8000
EPISIGNAL_DATABASE_URL=postgresql://postgres.PROJECT_REF:PASSWORD@REGION.pooler.supabase.com:5432/postgres
EPISIGNAL_CORS_ORIGINS=http://localhost:3000
EPISIGNAL_LOG_LEVEL=INFO
```

Create `apps/web/.env.local.example`:

```dotenv
NEXT_PUBLIC_EPISIGNAL_API_URL=http://127.0.0.1:8000
```

Create `.gitignore`:

```gitignore
.env
.env.*
!.env.example
!.env.local.example
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
coverage.xml
*.py[cod]
*.egg-info/
build/
dist/
node_modules/
.next/
coverage/
htmlcov/
.superpowers/
*.log
```

Create `.python-version` containing `3.12` and `.editorconfig` with UTF-8, LF, final newline, four spaces for Python, and two spaces for JSON/YAML/TypeScript/CSS.

- [x] **Step 5: Normalize generated web package metadata and install tooling**

Change `apps/web/package.json` name to `@episignal/web`, add scripts `"typecheck": "tsc --noEmit"` and `"test": "vitest run"`, and add `"@episignal/contracts": "workspace:*"` under dependencies. Create empty package markers at `apps/api/src/episignal_api/__init__.py` and `packages/backend/src/episignal_backend/__init__.py`, then run:

```powershell
pnpm --filter @episignal/web add -D prettier vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event vite-tsconfig-paths
pnpm install
uv sync
```

Expected: `pnpm-lock.yaml`, `uv.lock`, and `.venv` are created; dependency resolution succeeds.

- [x] **Step 6: Verify workspace discovery**

Run:

```powershell
pnpm list -r --depth -1
uv workspace list
```

Expected: pnpm lists `episignal`, `@episignal/web`, and `@episignal/contracts`; uv lists the root, `episignal-api`, and `episignal-backend`.

- [x] **Step 7: Commit**

```powershell
git add .gitignore .editorconfig .python-version package.json pnpm-workspace.yaml pyproject.toml pnpm-lock.yaml uv.lock apps packages
git commit -m "build: scaffold EpiSignal monorepo"
```

### Task 2: Implement safe backend configuration

**Files:**
- Create: `packages/backend/tests/test_config.py`
- Create: `packages/backend/src/episignal_backend/config.py`
- Modify: `packages/backend/src/episignal_backend/__init__.py`

- [x] **Step 1: Write failing configuration tests**

```python
from pydantic import ValidationError
import pytest

from episignal_backend.config import Settings, normalize_database_url


def test_normalizes_supabase_postgres_url_for_psycopg() -> None:
    assert normalize_database_url("postgresql://user:secret@host/db") == (
        "postgresql+psycopg://user:secret@host/db"
    )


def test_keeps_explicit_psycopg_url() -> None:
    url = "postgresql+psycopg://user:secret@host/db"
    assert normalize_database_url(url) == url


def test_rejects_non_postgresql_database_url() -> None:
    with pytest.raises(ValueError, match="EPISIGNAL_DATABASE_URL"):
        normalize_database_url("sqlite:///episignal.db")


@pytest.mark.parametrize(
    "value",
    [
        "postgresql://",
        "postgresql://user@host/database",
        "postgresql://user:password@/database",
        "postgresql://user:password@host",
    ],
)
def test_rejects_incomplete_postgresql_database_url(value: str) -> None:
    with pytest.raises(ValueError, match="EPISIGNAL_DATABASE_URL"):
        normalize_database_url(value)


def test_settings_reject_non_postgresql_database_url_during_creation() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite:///episignal.db", _env_file=None)


def test_settings_parse_comma_separated_cors_origins() -> None:
    settings = Settings(
        database_url="postgresql://user:secret@host/db",
        cors_origins="http://localhost:3000,https://episignal.example",
        _env_file=None,
    )
    assert settings.cors_origins == (
        "http://localhost:3000",
        "https://episignal.example",
    )


def test_settings_reject_invalid_cors_origin() -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql://user:secret@host/db",
            cors_origins="not-a-url",
            _env_file=None,
        )


def test_database_secret_is_not_exposed_by_repr() -> None:
    settings = Settings(database_url="postgresql://user:secret@host/db", _env_file=None)
    assert "secret" not in repr(settings)


def test_database_url_is_required() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

- [x] **Step 2: Run tests and confirm RED**

Run: `uv run pytest packages/backend/tests/test_config.py -v`

Expected: collection fails because `episignal_backend.config` does not exist.

- [x] **Step 3: Implement minimal validated settings**

```python
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BeforeValidator, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


def normalize_database_url(value: str) -> str:
    if value.startswith("postgres://"):
        normalized = value.replace("postgres://", "postgresql+psycopg://", 1)
    elif value.startswith("postgresql://"):
        normalized = value.replace("postgresql://", "postgresql+psycopg://", 1)
    elif value.startswith("postgresql+psycopg://"):
        normalized = value
    else:
        raise ValueError("EPISIGNAL_DATABASE_URL must use a PostgreSQL psycopg URL")
    try:
        url = make_url(normalized)
    except ArgumentError as error:
        raise ValueError("EPISIGNAL_DATABASE_URL is malformed") from error
    if not all((url.username, url.password, url.host, url.database)):
        raise ValueError("EPISIGNAL_DATABASE_URL requires credentials, host, and database")
    return normalized


def parse_origins(value: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return value
    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EPISIGNAL_",
        env_file="apps/api/.env",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    database_url: SecretStr
    cors_origins: Annotated[tuple[str, ...], BeforeValidator(parse_origins)] = (
        "http://localhost:3000",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        normalize_database_url(value.get_secret_value())
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("EPISIGNAL_CORS_ORIGINS must contain HTTP(S) origins")
        return values

    @property
    def sqlalchemy_database_url(self) -> str:
        return normalize_database_url(self.database_url.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [x] **Step 4: Run tests and confirm GREEN**

Run: `uv run pytest packages/backend/tests/test_config.py -v`

Expected: twelve tests pass and no secret appears in output.

- [x] **Step 5: Commit**

```powershell
git add packages/backend
git commit -m "feat: add safe backend configuration"
```

### Task 3: Define the epidemiological domain schema

**Files:**
- Create: `packages/backend/tests/test_models.py`
- Create: `packages/backend/src/episignal_backend/db/base.py`
- Create: `packages/backend/src/episignal_backend/db/types.py`
- Create: `packages/backend/src/episignal_backend/models/catalog.py`
- Create: `packages/backend/src/episignal_backend/models/signal.py`
- Create: `packages/backend/src/episignal_backend/models/event.py`
- Create: `packages/backend/src/episignal_backend/models/__init__.py`

- [x] **Step 1: Write failing metadata tests**

```python
from episignal_backend.db.base import Base
import episignal_backend.models  # noqa: F401


EXPECTED_TABLES = {
    "sources",
    "signals",
    "diseases",
    "pathogens",
    "events",
    "event_signals",
    "event_observations",
    "event_locations",
}


def test_metadata_contains_phase_one_tables() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_observations_preserve_event_and_signal_provenance() -> None:
    table = Base.metadata.tables["event_observations"]
    targets = {foreign_key.target_fullname for foreign_key in table.foreign_keys}
    assert "events.id" in targets
    assert "signals.id" in targets


def test_signal_original_url_is_unique_and_required() -> None:
    url = Base.metadata.tables["signals"].c.url
    assert url.nullable is False
    assert url.unique is True


def test_database_generates_uuid_primary_keys() -> None:
    source_id = Base.metadata.tables["sources"].c.id
    assert source_id.default is None
    assert str(source_id.server_default.arg) == "gen_random_uuid()"


def test_source_name_is_a_stable_unique_seed_key() -> None:
    name = Base.metadata.tables["sources"].c.name
    assert name.nullable is False
    assert name.unique is True


def test_catalog_natural_keys_and_source_urls_are_unique() -> None:
    assert Base.metadata.tables["sources"].c.base_url.unique is True
    assert Base.metadata.tables["sources"].c.feed_url.unique is True
    assert Base.metadata.tables["diseases"].c.slug.unique is True
    assert Base.metadata.tables["pathogens"].c.slug.unique is True


def test_event_signal_relationship_has_composite_primary_key() -> None:
    table = Base.metadata.tables["event_signals"]
    assert [column.name for column in table.primary_key.columns] == ["event_id", "signal_id"]


def test_location_uses_postgis_geography() -> None:
    assert str(Base.metadata.tables["event_locations"].c.geometry.type) == "geography(POINT,4326)"
```

- [x] **Step 2: Run tests and confirm RED**

Run: `uv run pytest packages/backend/tests/test_models.py -v`

Expected: import fails because the database model modules do not exist.

- [x] **Step 3: Implement shared SQLAlchemy primitives**

Create `db/base.py` with a `DeclarativeBase`, deterministic constraint naming, PostgreSQL-generated UUID primary-key mixin, and UTC `created_at`/`updated_at` mixin. Create `db/types.py` with these exact `StrEnum` vocabularies:

```text
SourceType: international_organization, regional_public_health_agency,
national_public_health_agency, ministry_of_health, scientific, humanitarian,
major_media, local_media, other
CredibilityTier: official, high, medium, unknown
SignalType: outbreak_report, surveillance_update, case_report, imported_case,
public_health_action, vaccination_campaign, risk_assessment, situation_report,
research, rumor, unknown
ProcessingStatus: fetched, normalized, classified, extracted, geocoded, matched,
published, failed, needs_review
EventType: outbreak, cluster, single_case, imported_case, seasonal_surveillance,
zoonotic_event, foodborne_outbreak, healthcare_associated_outbreak,
unknown_disease_event, other
EventStatus: monitoring, ongoing, expanding, stable, declining, resolved, unknown
VerificationStatus: officially_confirmed, high_credibility, signal, unverified,
rumor_monitoring
RelationshipType: initial_report, update, supporting_source, risk_assessment,
public_health_response, correction, background
LocationRole: primary, exposure, diagnosis, travel, reporting, affected_area
```

Use this exact base contract:

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, MetaData, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdentityMixin:
    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

- [x] **Step 4: Implement catalog and signal models**

Implement typed SQLAlchemy 2 models matching the approved design. Use PostgreSQL `ARRAY(Text)` for synonyms, `JSONB` for AI extraction, and `Enum(EnumClass, native_enum=False, create_constraint=True)` with stable names such as `source_type_values` and `event_status_values`. Use named `CheckConstraint` objects for every range. Confidence, relevance, extraction, geocoding, and match scores use `[0, 1]`; attention score uses `[0, 100]`; CFR is a percentage using `[0, 100]`; all case/death/recovery/hospitalization/affected-area counts are non-negative.

Required catalog columns:

```text
sources: id, name (unique), source_type, country_code, base_url (unique),
feed_url (unique when present),
credibility_tier, is_official, language, active, created_at, updated_at
diseases: id, canonical_name, slug (unique), icd10, synonyms, category, created_at, updated_at
pathogens: id, canonical_name, slug (unique), taxonomy, synonyms, created_at, updated_at
```

Required signal columns:

```text
id, source_id, external_id, url, canonical_url, title, raw_text, summary,
published_at, retrieved_at, language, content_hash, relevance_score,
public_health_relevant, signal_type, ai_extraction, ai_model,
ai_processed_at, processing_status, created_at, updated_at
```

Define `url` as `Text(nullable=False, unique=True)` and index `source_id`, `published_at`, `canonical_url`, `content_hash`, and `processing_status`.

- [x] **Step 5: Implement event, relationship, observation, and location models**

Required event columns:

```text
id, public_id, slug, title, disease_id, pathogen_id, event_type, status,
verification_status, country_code, admin1, admin2, latitude, longitude,
geometry, first_signal_at, event_start_date, last_updated_at,
attention_score, confidence_score, ai_summary, created_at, updated_at
```

Required relationship columns:

```text
event_id, signal_id, relationship_type, match_score, is_primary, created_at
```

Required observation columns:

```text
id, event_id, signal_id, observation_date, reported_at, suspected_cases,
probable_cases, confirmed_cases, total_cases, new_cases, deaths, new_deaths,
recoveries, hospitalizations, cfr, affected_admin_areas, notes,
extraction_confidence, created_at
```

Required location columns:

```text
id, event_id, location_role, country_code, admin1, admin2, place_name,
latitude, longitude, geometry, geocoding_source, geocoding_confidence, created_at
```

Use `Geography(geometry_type="POINT", srid=4326, spatial_index=False)` and explicit GiST indexes for event and location geometry. Define exact B-tree indexes named `ix_events_status`, `ix_events_verification_status`, `ix_events_disease_id`, `ix_events_country_code`, `ix_events_last_updated_at`, `ix_signals_source_id`, `ix_signals_published_at`, `ix_signals_processing_status`, `ix_signals_canonical_url`, `ix_signals_content_hash`, and compound `ix_event_observations_event_date` on `(event_id, observation_date)`. Exporting model metadata must show every enum check, unique event `public_id` and slug, unique catalog slugs and source URLs, unique source name and signal URL, the relationship composite primary key, all required foreign keys, named range checks, named indexes, and PostgreSQL UUID server defaults.

- [x] **Step 6: Export every model and run tests**

Import all eight mapped classes from `models/__init__.py`, then run:

```powershell
uv run pytest packages/backend/tests/test_models.py -v
uv run mypy packages/backend/src
uv run ruff check packages/backend
```

Expected: eight tests pass; mypy and Ruff report no issues.

- [x] **Step 7: Commit**

```powershell
git add packages/backend
git commit -m "feat: model epidemiological provenance"
```

### Task 4: Add immutable Alembic schema history

**Files:**
- Create: `database/alembic.ini`
- Create: `database/migrations/env.py`
- Create: `database/migrations/script.py.mako`
- Create: `database/migrations/versions/20260826_0001_core_schema.py`
- Create: `apps/api/tests/test_migrations.py`

- [x] **Step 1: Write a failing migration-structure test**

```python
from pathlib import Path
import subprocess
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migrations_have_one_linear_head() -> None:
    root = Path(__file__).parents[3]
    config = Config(root / "database" / "alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20260826_0001"]


def render_offline(*arguments: str) -> str:
    root = Path(__file__).parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "database/alembic.ini",
            *arguments,
            "--sql",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.lower()


def test_offline_upgrade_declares_every_core_invariant() -> None:
    sql = render_offline("upgrade", "head")
    for table in (
        "sources",
        "signals",
        "diseases",
        "pathogens",
        "events",
        "event_signals",
        "event_observations",
        "event_locations",
    ):
        assert f"create table {table}" in sql
    for fragment in (
        "gen_random_uuid()",
        "uq_sources_name",
        "uq_sources_base_url",
        "uq_sources_feed_url",
        "uq_signals_url",
        "uq_diseases_slug",
        "uq_pathogens_slug",
        "uq_events_public_id",
        "uq_events_slug",
        "pk_event_signals",
        "source_type_values",
        "credibility_tier_values",
        "signal_type_values",
        "processing_status_values",
        "event_type_values",
        "event_status_values",
        "verification_status_values",
        "relationship_type_values",
        "location_role_values",
        "ck_signals_relevance_score_range",
        "ck_events_attention_score_range",
        "ck_events_confidence_score_range",
        "ck_event_signals_match_score_range",
        "ck_event_observations_suspected_cases_non_negative",
        "ck_event_observations_probable_cases_non_negative",
        "ck_event_observations_confirmed_cases_non_negative",
        "ck_event_observations_total_cases_non_negative",
        "ck_event_observations_new_cases_non_negative",
        "ck_event_observations_deaths_non_negative",
        "ck_event_observations_new_deaths_non_negative",
        "ck_event_observations_recoveries_non_negative",
        "ck_event_observations_hospitalizations_non_negative",
        "ck_event_observations_affected_admin_areas_non_negative",
        "ck_event_observations_cfr_range",
        "ck_event_observations_extraction_confidence_range",
        "ck_event_locations_geocoding_confidence_range",
        "ix_events_status",
        "ix_events_verification_status",
        "ix_events_disease_id",
        "ix_events_country_code",
        "ix_events_last_updated_at",
        "ix_signals_source_id",
        "ix_signals_published_at",
        "ix_signals_processing_status",
        "ix_signals_canonical_url",
        "ix_signals_content_hash",
        "ix_event_observations_event_date",
        "ix_events_geometry",
        "ix_event_locations_geometry",
    ):
        assert fragment in sql


def test_offline_downgrade_drops_dependents_before_parents() -> None:
    sql = render_offline("downgrade", "20260826_0001:base")
    assert sql.index("drop table event_locations") < sql.index("drop table events")
    assert sql.index("drop table event_observations") < sql.index("drop table events")
    assert "drop extension postgis" not in sql
```

- [x] **Step 2: Run test and confirm RED**

Run: `uv run pytest apps/api/tests/test_migrations.py -v`

Expected: failure because `database/alembic.ini` does not exist.

- [x] **Step 3: Configure Alembic without storing a URL**

Set `script_location = %(here)s/migrations` in `database/alembic.ini`. In `env.py`, import `Base`, load all models, and configure `compare_type=True`. Online mode must obtain `get_settings().sqlalchemy_database_url` and redact it from logging. Offline mode must not instantiate `Settings`; use `postgresql+psycopg://offline:offline@localhost/offline` only as a dialect selector so SQL rendering needs no credentials or network.

- [x] **Step 4: Create and review the explicit initial revision**

Create revision `20260826_0001` with message `create core epidemiology schema`. Its `upgrade()` must:

1. execute `CREATE EXTENSION IF NOT EXISTS postgis`;
2. create the eight tables in foreign-key order using explicit `op.create_table` calls;
3. create every B-tree and GiST index declared by the model metadata;
4. use fixed constraint and index names matching `Base.metadata`.

Its `downgrade()` must drop indexes and tables in reverse dependency order but must not remove PostGIS, because the hosted project may share that extension with other schemas.

Generate upgrade and downgrade SQL artifacts without contacting Supabase:

```powershell
uv run --package episignal-api alembic -c database/alembic.ini upgrade head --sql *> $env:TEMP\episignal-foundation.sql
uv run --package episignal-api alembic -c database/alembic.ini downgrade 20260826_0001:base --sql *> $env:TEMP\episignal-foundation-down.sql
Select-String -Path $env:TEMP\episignal-foundation.sql -Pattern 'CREATE TABLE events','CREATE TABLE event_observations','ix_event_locations_geometry','gen_random_uuid'
Select-String -Path $env:TEMP\episignal-foundation-down.sql -Pattern 'DROP TABLE event_locations','DROP TABLE events'
```

Expected: all upgrade and downgrade patterns are present; neither command reads `apps/api/.env` or contacts a database.

- [x] **Step 5: Run migration test and static checks**

Run:

```powershell
uv run pytest apps/api/tests/test_migrations.py -v
uv run ruff check database apps/api/tests/test_migrations.py
```

Expected: all three migration tests pass and Ruff is clean.

- [x] **Step 6: Commit**

```powershell
git add database apps/api/tests/test_migrations.py
git commit -m "feat: add core PostGIS migration"
```

### Task 5: Add deterministic disease and source seeds

**Files:**
- Create: `database/seeds/diseases.json`
- Create: `database/seeds/sources.json`
- Create: `packages/backend/tests/test_seeds.py`
- Create: `packages/backend/src/episignal_backend/seeds.py`
- Create: `packages/backend/src/episignal_backend/seed_runner.py`

- [x] **Step 1: Add reviewed seed datasets**

`diseases.json` must contain these unique canonical identities and kebab-case slugs:

```text
Cholera, Dengue, Measles, Mpox, Ebola virus disease, Marburg virus disease,
Yellow fever, West Nile virus disease, Chikungunya, Avian influenza,
Seasonal influenza, COVID-19, MERS, Lassa fever, Rift Valley fever, Polio,
Diphtheria, Pertussis, Meningococcal disease, Anthrax, Hantavirus infection,
Leptospirosis, Malaria, Zika virus disease, Typhoid fever, Salmonellosis,
Unknown respiratory illness, Unknown febrile illness, Unknown disease
```

`sources.json` must define `WHO Disease Outbreak News` and `ECDC`, both official but inactive source identities with stable base/feed URLs and no connector-specific state. Connectors activate them only in the later ingestion slice.

- [x] **Step 2: Write failing seed tests**

```python
from episignal_backend.seeds import load_diseases, load_sources


def test_disease_seed_natural_keys_are_unique() -> None:
    diseases = load_diseases()
    assert len(diseases) == 29
    assert len({item.slug for item in diseases}) == len(diseases)
    assert {item.canonical_name for item in diseases} >= {
        "Cholera",
        "Dengue",
        "Unknown disease",
    }


def test_source_seeds_are_official_and_unique() -> None:
    sources = load_sources()
    assert {item.name for item in sources} == {"WHO Disease Outbreak News", "ECDC"}
    assert all(item.is_official for item in sources)
    assert all(item.active is False for item in sources)
```

- [x] **Step 3: Run tests and confirm RED**

Run: `uv run pytest packages/backend/tests/test_seeds.py -v`

Expected: import fails because `episignal_backend.seeds` does not exist.

- [x] **Step 4: Implement validated loading and upsert statements**

Define strict Pydantic `DiseaseSeed` and `SourceSeed` models, load JSON relative to the repository root, and build PostgreSQL upserts using `diseases.slug` and `sources.name` as stable natural keys. Exclude `id`, `created_at`, and each natural key from updates. Use this implementation shape:

```python
def _read_seed(name: str) -> object:
    path = Path(__file__).parents[4] / "database" / "seeds" / name
    return json.loads(path.read_text(encoding="utf-8"))


def load_diseases() -> tuple[DiseaseSeed, ...]:
    return tuple(TypeAdapter(list[DiseaseSeed]).validate_python(_read_seed("diseases.json")))


def load_sources() -> tuple[SourceSeed, ...]:
    return tuple(TypeAdapter(list[SourceSeed]).validate_python(_read_seed("sources.json")))


def _upsert(
    session: Session,
    model: type[Disease] | type[Source],
    rows: list[dict[str, object]],
    natural_key: str,
) -> None:
    statement = insert(model).values(rows)
    updates = {
        column.name: getattr(statement.excluded, column.name)
        for column in model.__table__.columns
        if column.name not in {"id", "created_at", natural_key}
    }
    session.execute(
        statement.on_conflict_do_update(
            index_elements=[getattr(model, natural_key)],
            set_=updates,
        )
    )


def seed_database(session: Session) -> SeedResult:
    diseases = load_diseases()
    sources = load_sources()
    _upsert(session, Disease, [item.model_dump() for item in diseases], "slug")
    _upsert(session, Source, [item.model_dump() for item in sources], "name")
    return SeedResult(diseases=len(diseases), sources=len(sources))
```

`SeedResult` contains the number of canonical disease and source identities processed. `seed_runner.py` opens one transaction, calls `seed_database`, prints only counts, and returns a non-zero exit code on failure.

- [x] **Step 5: Run tests and confirm GREEN**

Run: `uv run pytest packages/backend/tests/test_seeds.py -v`

Expected: two tests pass, including inactive connector assertions.

- [x] **Step 6: Commit**

```powershell
git add database/seeds packages/backend
git commit -m "feat: add canonical epidemiology seeds"
```

### Task 6: Implement database readiness and the FastAPI contract

**Files:**
- Create: `packages/backend/tests/test_health.py`
- Create: `packages/backend/src/episignal_backend/db/session.py`
- Create: `packages/backend/src/episignal_backend/health.py`
- Create: `apps/api/tests/test_api.py`
- Create: `apps/api/src/episignal_api/dependencies.py`
- Create: `apps/api/src/episignal_api/middleware.py`
- Create: `apps/api/src/episignal_api/routes/health.py`
- Create: `apps/api/src/episignal_api/routes/version.py`
- Create: `apps/api/src/episignal_api/factory.py`
- Create: `apps/api/src/episignal_api/main.py`
- Create: `apps/api/src/episignal_api/run.py`
- Create: `apps/api/src/episignal_api/database_check.py`

- [x] **Step 1: Write failing backend health tests**

```python
from episignal_backend.health import DatabaseHealth, check_database


class HealthyConnection:
    def scalar(self, statement: object) -> object:
        sql = str(statement)
        return "3.5 USE_GEOS=1" if "postgis_full_version" in sql else 1


class BrokenConnection:
    def scalar(self, statement: object) -> object:
        raise TimeoutError("database unavailable")


def test_database_health_requires_postgis() -> None:
    assert check_database(HealthyConnection()) == DatabaseHealth(
        database="up", postgis="up"
    )


def test_database_health_sanitizes_connection_failures() -> None:
    result = check_database(BrokenConnection())
    assert result.database == "down"
    assert result.postgis == "unknown"
    assert "unavailable" not in repr(result)
```

- [x] **Step 2: Run backend tests and confirm RED**

Run: `uv run pytest packages/backend/tests/test_health.py -v`

Expected: import fails because `health.py` does not exist.

- [x] **Step 3: Implement engine/session factories and health checking**

Create a lazy SQLAlchemy engine with `pool_pre_ping=True`, `pool_size=5`, `max_overflow=5`, and `connect_timeout=5`. Expose context-managed connections and sessions. `check_database` executes `SELECT 1` and `SELECT postgis_full_version()` and returns only component states; it never returns exception text, URL, hostname, or PostGIS build details.

- [x] **Step 4: Write failing API contract tests**

```python
import os
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from episignal_api.dependencies import get_database_health
from episignal_api.factory import create_app
from episignal_backend.config import Settings
from episignal_backend.health import DatabaseHealth


TEST_SETTINGS = Settings(
    database_url="postgresql://test:test@localhost/test",
    _env_file=None,
)


def make_app() -> FastAPI:
    return create_app(TEST_SETTINGS)


def test_liveness_does_not_require_database() -> None:
    client = TestClient(make_app())
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_returns_503_for_database_failure() -> None:
    app = make_app()
    app.dependency_overrides[get_database_health] = lambda: DatabaseHealth(
        database="down", postgis="unknown"
    )
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "components": {"database": "down", "postgis": "unknown"},
        "error_code": "DATABASE_NOT_READY",
    }


def test_readiness_returns_component_success() -> None:
    app = make_app()
    app.dependency_overrides[get_database_health] = lambda: DatabaseHealth(
        database="up", postgis="up"
    )
    response = TestClient(app).get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "components": {"database": "up", "postgis": "up"},
    }


def test_version_endpoint_is_namespaced() -> None:
    response = TestClient(make_app()).get("/api/v1")
    assert response.status_code == 200
    assert response.json() == {"name": "EpiSignal API", "version": "0.1.0"}


def test_valid_inbound_request_id_is_propagated() -> None:
    request_id = "b4caace5-3afb-4a43-b2d8-ec0d8d5042ca"
    response = TestClient(make_app()).get(
        "/health/live", headers={"X-Request-ID": request_id}
    )
    assert response.headers["X-Request-ID"] == request_id


def test_invalid_request_id_is_replaced() -> None:
    response = TestClient(make_app()).get(
        "/health/live", headers={"X-Request-ID": "not-a-uuid"}
    )
    assert response.headers["X-Request-ID"] != "not-a-uuid"


def test_openapi_and_docs_are_available() -> None:
    client = TestClient(make_app())
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_production_entrypoint_fails_safely_without_database_url(tmp_path) -> None:
    environment = os.environ.copy()
    environment.pop("EPISIGNAL_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-c", "import episignal_api.main"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "EPISIGNAL_DATABASE_URL" in result.stderr
    assert "postgresql://" not in result.stderr


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("EPISIGNAL_DATABASE_URL", "sqlite:///private.db"),
        ("EPISIGNAL_API_PORT", "not-a-port"),
    ],
)
def test_production_entrypoint_names_actual_invalid_setting(
    tmp_path, setting: str, value: str
) -> None:
    environment = os.environ.copy()
    environment["EPISIGNAL_DATABASE_URL"] = "postgresql://test:test@localhost/test"
    environment[setting] = value
    result = subprocess.run(
        [sys.executable, "-c", "import episignal_api.main"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert setting in result.stderr
    assert value not in result.stderr


def test_unexpected_error_is_sanitized_and_correlated(caplog) -> None:
    app = make_app()

    @app.get("/explode")
    def explode() -> None:
        raise RuntimeError("private database detail")

    response = TestClient(app, raise_server_exceptions=False).get("/explode")
    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_SERVER_ERROR"
    assert "private database detail" not in response.text
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert response.headers["X-Request-ID"] in caplog.text
```

- [x] **Step 5: Run API tests and confirm RED**

Run: `uv run pytest apps/api/tests/test_api.py -v`

Expected: import fails because the API modules do not exist.

- [x] **Step 6: Implement the app factory, routes, and request IDs**

Use Pydantic response models. `factory.create_app(settings: Settings)` requires already validated settings but does not connect to the database. Add CORS from those settings, add request-ID middleware that accepts a valid inbound UUID or creates `uuid4()`, include the health and v1 routers, log unexpected exceptions with the request ID, and register a sanitized catch-all exception handler returning:

```json
{
  "error_code": "INTERNAL_SERVER_ERROR",
  "message": "An unexpected error occurred.",
  "request_id": "b4caace5-3afb-4a43-b2d8-ec0d8d5042ca"
}
```

Use dependency injection for `get_database_health` so unit tests never access Supabase. Add `load_runtime_settings()` that converts each missing or invalid setting into concise stderr guidance naming the actual `EPISIGNAL_` environment field derived from Pydantic's error location, without printing rejected values. `main.py` must contain `app = create_app(load_runtime_settings())`; importing the production entry point therefore fails immediately when configuration is missing or invalid. `run.py` reads the same validated settings and starts Uvicorn using `api_host`, `api_port`, and `log_level`. `database_check.py` performs the same readiness call for `pnpm db:check`, labels failures as `configuration`, `connection`, or `postgis`, and exits 1 unless both components are up.

- [x] **Step 7: Run all backend checks**

Run:

```powershell
uv run pytest packages/backend/tests apps/api/tests -v
uv run ruff check packages/backend apps/api
uv run mypy packages/backend/src apps/api/src
```

Expected: all tests pass; Ruff and mypy are clean.

- [x] **Step 8: Commit**

```powershell
git add packages/backend apps/api
git commit -m "feat: expose API health and readiness"
```

### Task 7: Generate and verify OpenAPI contracts

**Files:**
- Create: `apps/api/src/episignal_api/export_openapi.py`
- Create: `packages/contracts/openapi.json`
- Create: `packages/contracts/src/index.d.ts`
- Create: `apps/api/tests/test_openapi.py`

- [x] **Step 1: Write a failing OpenAPI stability test**

```python
from episignal_api.factory import create_app
from episignal_backend.config import Settings


def test_openapi_exposes_only_foundation_routes() -> None:
    settings = Settings(
        database_url="postgresql://openapi:openapi@localhost/openapi",
        _env_file=None,
    )
    paths = set(create_app(settings).openapi()["paths"])
    assert paths == {"/health/live", "/health/ready", "/api/v1"}
```

- [x] **Step 2: Run test and confirm expected state**

Run: `uv run pytest apps/api/tests/test_openapi.py -v`

Expected: pass only if the API task exposed exactly the approved routes; otherwise correct route registration before continuing.

- [x] **Step 3: Implement deterministic export and generation**

`export_openapi.py` must create the app with the same non-secret dialect-only settings used by the OpenAPI test, then serialize its schema with sorted keys and two-space indentation to `packages/contracts/openapi.json`, ending with one newline. It must not import `episignal_api.main`, read `.env`, or contact a database. Run:

```powershell
pnpm contracts:generate
pnpm contracts:check
```

Expected: `src/index.d.ts` is generated and the second command produces no Git diff after generation.

- [x] **Step 4: Commit**

```powershell
git add apps/api packages/contracts pnpm-lock.yaml
git commit -m "build: generate typed API contracts"
```

### Task 8: Build the responsive public shell test-first

**Files:**
- Create: `apps/web/vitest.config.ts`
- Create: `apps/web/src/test/setup.ts`
- Create: `apps/web/src/components/home-shell.test.tsx`
- Create: `apps/web/src/components/home-shell.tsx`
- Create: `apps/web/src/lib/api-health.test.ts`
- Create: `apps/web/src/lib/api-health.ts`
- Create: `apps/web/src/app/loading.tsx`
- Modify: `apps/web/src/app/page.tsx`
- Modify: `apps/web/src/app/layout.tsx`
- Modify: `apps/web/src/app/globals.css`

- [x] **Step 1: Configure Vitest**

```typescript
// vitest.config.ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";

export default defineConfig({
  plugins: [react(), tsconfigPaths()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
```

Install `@vitejs/plugin-react`, and import `@testing-library/jest-dom/vitest` from `src/test/setup.ts`.

- [x] **Step 2: Write failing shell accessibility tests**

```tsx
import { render, screen } from "@testing-library/react";
import { HomeShell } from "./home-shell";


test("renders an honest evidence-free foundation shell", () => {
  render(<HomeShell apiStatus="ready" />);
  expect(screen.getByRole("banner")).toBeInTheDocument();
  expect(screen.getByRole("main")).toBeInTheDocument();
  expect(screen.getByRole("searchbox")).toBeDisabled();
  expect(screen.getByText("Event records will appear after source ingestion is connected."))
    .toBeInTheDocument();
  expect(screen.queryByText(/cases|deaths/i)).not.toBeInTheDocument();
});


test("shows API unavailability without hiding the product shell", () => {
  render(<HomeShell apiStatus="unavailable" />);
  expect(screen.getByText("API unavailable")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /what is happening/i })).toBeInTheDocument();
});


test("shows loading state in the same stable shell", () => {
  render(<HomeShell apiStatus="loading" />);
  expect(screen.getByText("Checking API")).toBeInTheDocument();
  expect(screen.getByRole("main")).toBeInTheDocument();
});


test("marks the mobile readiness panel as a bottom sheet", () => {
  render(<HomeShell apiStatus="ready" />);
  expect(screen.getByLabelText("Foundation status")).toHaveAttribute(
    "data-mobile-role",
    "bottom-sheet",
  );
});
```

- [x] **Step 3: Run shell test and confirm RED**

Run: `pnpm --filter @episignal/web test -- src/components/home-shell.test.tsx`

Expected: import fails because `home-shell.tsx` does not exist.

- [x] **Step 4: Implement the semantic shell**

Create `HomeShell` with `apiStatus: "loading" | "ready" | "unavailable"`. Map those states to `Checking API`, `API connected`, and `API unavailable`. It must render:

```tsx
<>
  <header className="masthead">
    <a className="brand" href="/">EpiSignal</a>
    <nav aria-label="Primary navigation">
      <a href="#explore">Explore</a>
      <a href="#data">Data</a>
      <a href="#about">About</a>
    </nav>
    <span className={`system-pill system-pill--${apiStatus}`}>{statusLabel}</span>
  </header>
  <main>
    <section className="hero" aria-labelledby="hero-title">
      <p className="eyebrow">Open global outbreak intelligence</p>
      <h1 id="hero-title">What is happening in infectious disease right now?</h1>
      <form className="search-preview" role="search" aria-label="Event search preview">
        <input type="search" disabled placeholder="Search disease, country, outbreak, pathogen…" />
        <button type="submit" disabled>Search</button>
      </form>
      <p className="preview-note">Search becomes available when the first evidence source is connected.</p>
    </section>
    <section id="explore" className="explore-grid" aria-label="Global activity">
      <div className="map-placeholder">
        <p className="map-label">Global activity map</p>
        <p>Event records will appear after source ingestion is connected.</p>
      </div>
      <aside
        className="readiness-card"
        aria-label="Foundation status"
        data-mobile-role="bottom-sheet"
      >
        <p className="eyebrow">System status</p>
        <h2>Ready for evidence.</h2>
        <p>The public shell is online. Connect the first source to begin building traceable events.</p>
        <p className="components">Database · PostGIS · API</p>
      </aside>
    </section>
  </main>
</>
```

Implement the approved warm off-white, navy, and teal tokens in `globals.css`. Use CSS Grid for the desktop explore area; below 760px switch to a full-width map and overlapping rounded readiness sheet. Preserve visible keyboard focus, minimum 44px interactive targets, readable contrast, and `prefers-reduced-motion` behavior. Do not add event numbers, severity colors, or sample outbreak cards.

- [x] **Step 5: Run shell tests and confirm GREEN**

Run: `pnpm --filter @episignal/web test -- src/components/home-shell.test.tsx`

Expected: four tests pass.

- [x] **Step 6: Write failing API health client tests**

```typescript
import { afterEach, expect, test, vi } from "vitest";
import { getApiStatus } from "./api-health";

afterEach(() => vi.unstubAllGlobals());

test("returns ready for a ready API", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "ready",
        components: { database: "up", postgis: "up" },
      }),
    }),
  );
  await expect(getApiStatus()).resolves.toBe("ready");
});

test("returns unavailable instead of throwing", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  await expect(getApiStatus()).resolves.toBe("unavailable");
});
```

- [x] **Step 7: Run client tests and confirm RED**

Run: `pnpm --filter @episignal/web test -- src/lib/api-health.test.ts`

Expected: import fails because `api-health.ts` does not exist.

- [x] **Step 8: Implement the bounded server-side health client**

```typescript
import type { paths } from "@episignal/contracts";

type ReadyResponse = paths["/health/ready"]["get"]["responses"][200]["content"]["application/json"];
export type ApiStatus = "ready" | "unavailable";

export async function getApiStatus(): Promise<ApiStatus> {
  const baseUrl = process.env.NEXT_PUBLIC_EPISIGNAL_API_URL ?? "http://127.0.0.1:8000";
  try {
    const response = await fetch(`${baseUrl}/health/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2500),
    });
    if (!response.ok) return "unavailable";
    const body = (await response.json()) as ReadyResponse;
    return body.status === "ready" ? "ready" : "unavailable";
  } catch {
    return "unavailable";
  }
}
```

Make `page.tsx` an async server component that calls `getApiStatus()` and passes the result to `HomeShell`. Make `loading.tsx` render `<HomeShell apiStatus="loading" />`, giving App Router a stable loading shell during the readiness request. In `layout.tsx`, define descriptive metadata and load one editorial display font plus one sans-serif UI font through `next/font` without runtime network requests.

- [x] **Step 9: Run frontend verification**

Run:

```powershell
pnpm --filter @episignal/web test
pnpm --filter @episignal/web lint
pnpm --filter @episignal/web typecheck
pnpm --filter @episignal/web build
```

Expected: tests, lint, type-check, and production build all pass with no warnings.

- [x] **Step 10: Commit**

```powershell
git add apps/web pnpm-lock.yaml
git commit -m "feat: build responsive public foundation shell"
```

### Task 9: Add safe Supabase setup and live smoke verification

**Files:**
- Create: `scripts/verify-live-database.ps1`
- Create: `docs/architecture/supabase-setup.md`
- Create: `README.md`

- [x] **Step 1: Implement a fail-fast live verification script**

`verify-live-database.ps1` must:

1. resolve the workspace root from `$PSScriptRoot` without using `$HOME`;
2. require `apps/api/.env` and print only the missing path when absent;
3. run `pnpm db:check` and stop on non-zero exit;
4. run `pnpm db:migrate` and stop on non-zero exit;
5. run `pnpm db:seed` once and capture `{slug: id}` for every canonical disease plus `{name: id}` for each canonical source;
6. run `pnpm db:seed` again and capture the same identity maps;
7. assert both identity maps are unchanged, the 29 canonical seed slugs each have multiplicity one, both canonical sources occur once, and both sources remain inactive; allow additional locally created disease rows outside the canonical seed set;
8. call a Python verification module that also asserts PostGIS exists and all eight tables exist;
9. print a concise success summary without connection details.

Use `$ErrorActionPreference = "Stop"` and direct `& pnpm ...` invocations with `$LASTEXITCODE` checks. The script must not create, delete, reset, or drop a Supabase project.

- [x] **Step 2: Document Supabase connection modes accurately**

`docs/architecture/supabase-setup.md` must explain:

- direct port 5432 is preferred for migrations when IPv6 is available;
- shared pooler session mode on port 5432 is the persistent API fallback for IPv4-only networks;
- transaction mode on port 6543 is not the default for this long-running local API;
- the password must be URL-encoded inside a string URL;
- PostGIS is enabled in the Supabase dashboard before migration;
- `.env` is ignored and must never be pasted into issues, logs, or browser settings.

Include exact commands:

```powershell
Copy-Item apps/api/.env.example apps/api/.env
Copy-Item apps/web/.env.local.example apps/web/.env.local
pnpm db:check
pnpm db:migrate
pnpm db:seed
pwsh -File scripts/verify-live-database.ps1
```

- [x] **Step 3: Write the root README**

The README must contain: product principle, current foundation scope, prerequisites, workspace map, Windows quick start, environment setup, local URLs, quality commands, live database safety warning, source-provenance model, and link to the approved design. It must say explicitly that the repository does not contain live ingestion or fabricated outbreak data yet.

- [x] **Step 4: Run the credential-free verification suite**

Run:

```powershell
pnpm verify
git status --short
```

Expected: all format, lint, type-check, tests, contract checks, and production build pass. Git status contains only intentional documentation changes before commit and no `.env` files.

- [x] **Step 5: Run the live smoke test only after the user configures Supabase**

Run: `pwsh -File scripts/verify-live-database.ps1`

Expected: the script reports database, PostGIS, eight tables, 29 stable disease identities, and two stable inactive source identities as ready. If credentials are not yet configured, record this single check as pending without weakening any credential-free acceptance test.

- [x] **Step 6: Commit**

```powershell
git add -- README.md docs/architecture scripts
git commit -m "docs: add lean Supabase development guide"
```

### Task 10: Final audit and handoff

**Files:**
- Modify only files that fail the checks below.

- [x] **Step 1: Run the full deterministic verification again**

```powershell
pnpm verify
```

Expected: exit code 0 with clean formatter, linters, type-checkers, tests, contract drift check, and Next.js production build.

- [x] **Step 2: Audit secrets and generated artifacts**

Run:

```powershell
git status --short --ignored
git grep -n -I -E 'postgres(ql)?://[^[:space:]]+:[^[:space:]]+@|SUPABASE_SERVICE_ROLE|EPISIGNAL_DATABASE_URL=.+'
rg -n -i 'EPISIGNAL_DATABASE_URL|postgres(ql)?://|db\.[a-z0-9]+\.supabase\.co' apps/web/.next/static
```

Expected: local environment files appear ignored; `git grep` finds only safe placeholders and documentation examples. The `.next/static` scan exits 1 because browser assets contain no database URL, Supabase database host, or private setting name.

- [x] **Step 3: Confirm API and web behavior locally**

Start `pnpm dev`, then verify:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/api/v1
Invoke-WebRequest http://localhost:3000 -UseBasicParsing | Select-Object StatusCode
```

Expected: with a valid `.env`, liveness reports `alive`, API metadata reports version `0.1.0`, and the web request returns 200. Invalid or missing configuration prevents API startup; a configured but unreachable database produces readiness 503.

- [x] **Step 4: Inspect repository history and status**

Run:

```powershell
git log --oneline --decorate -10
git status --short --branch
```

Expected: task commits are present, the branch is `main`, and the worktree is clean.

- [ ] **Step 5: Create a final fixes commit only if verification required changes**

Run `git diff --name-only`, inspect every listed path, and stage each approved plan-owned path individually with `git add --` followed by its literal path. Never use `git add -A` or stage unrelated user files. Commit with `git commit -m "fix: complete foundation verification"`. Skip this commit when no files changed.

## Primary References

- Next.js create-next-app: https://nextjs.org/docs/app/api-reference/cli/create-next-app
- Next.js installation and Node requirements: https://nextjs.org/docs/app/getting-started/installation
- uv workspaces: https://docs.astral.sh/uv/concepts/projects/workspaces/
- FastAPI testing: https://fastapi.tiangolo.com/tutorial/testing/
- FastAPI dependency overrides: https://fastapi.tiangolo.com/advanced/testing-dependencies/
- FastAPI error handling: https://fastapi.tiangolo.com/tutorial/handling-errors/
- SQLAlchemy psycopg dialect: https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#psycopg
- Supabase PostgreSQL connection modes: https://supabase.com/docs/guides/database/connecting-to-postgres
