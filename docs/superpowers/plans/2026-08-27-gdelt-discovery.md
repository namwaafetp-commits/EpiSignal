# GDELT Discovery Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover news articles through the GDELT DOC 2.0 API and store each one as a signal attributed to the publisher that actually wrote it, with its original URL, its own body text, and four separately recorded timestamps.

**Architecture:** A second ingestion pipeline, `run_discovery`, sits beside the existing `run_ingestion`. `run_ingestion` resolves one source per run from a connector name, which suits WHO and ECDC. `run_discovery` resolves a publisher per document, because GDELT surfaces articles from thousands of unknown domains. Both share URL canonicalization, content fingerprinting, and the `signals` table. GDELT returns no publication date and no article text, so the connector fetches the publisher's own page for both.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, Alembic, Pydantic v2, pydantic-settings, httpx, pytest, mypy strict, ruff. No new dependency is added: HTML is parsed with the standard library `html.parser`, matching `ingestion/html_text.py`.

---

## Required reading before Task 1

Read these first. They are short, and every task below assumes them.

- `docs/superpowers/specs/2026-08-27-gdelt-discovery-design.md` — the approved design for this plan.
- `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md` — the invariants later sub-projects depend on.
- `packages/backend/src/episignal_backend/ingestion/protocol.py` — the existing boundaries.
- `packages/backend/src/episignal_backend/ingestion/pipeline.py` — the pipeline `run_discovery` is modelled on.
- `packages/backend/src/episignal_backend/ingestion/who_don.py` — the connector pattern, including retry and the pure-`normalize` rule.
- `AGENTS.md` — repository-wide agent instructions.

## Conventions this repository already enforces

Violating any of these will fail `pnpm verify`.

- **mypy runs in strict mode.** Every function needs annotations. No implicit `Any`.
- **ruff, line length 100**, rules `E, F, I, UP, B, SIM`.
- **Comments explain why, not what.** Existing modules do this consistently; match the tone. Do not add narration comments.
- **Tests never need credentials or network.** Connectors are tested with fake transports and committed fixtures.
- **Modules that open sockets are isolated.** Only `gdelt/api.py` and `gdelt/article.py` may make a request. `discovery.py` imports neither `httpx` nor SQLAlchemy.
- **Timestamps are timezone-aware.** Naive datetimes are rejected at the boundary.
- **Never print payload bodies or the connection string.** Runners print counts only.

## Commands

Run from the repository root, `D:\Projects\Side Project\EpiSignal`.

```powershell
uv run pytest packages/backend/tests/test_gdelt_locale.py -v   # one test file
uv run pytest                                                  # all Python tests
uv run ruff check .
uv run ruff format .
uv run mypy apps/api/src packages/backend/src
```

`pnpm` is not on PATH in every shell here. If `pnpm` is not found, use
`npx --yes pnpm@11.19.0 <script>` instead.

**Known pre-existing failure:** `pnpm format:check` fails on 18 files on `main`
because of a CRLF line-ending mismatch in this checkout. It is unrelated to this
work and is not yours to fix. Verify with `uv run pytest`, `uv run ruff check .`,
and `uv run mypy` instead of the full `pnpm verify`.

## File Structure

**Created:**

| Path | Responsibility |
| --- | --- |
| `packages/backend/src/episignal_backend/models/discovery.py` | The `GdeltQueryRule` model. |
| `packages/backend/src/episignal_backend/ingestion/gdelt/__init__.py` | Package marker. |
| `packages/backend/src/episignal_backend/ingestion/gdelt/locale.py` | Pure: GDELT language and country names to codes. |
| `packages/backend/src/episignal_backend/ingestion/gdelt/extract.py` | Pure: HTML to title, publication time, site name, body. |
| `packages/backend/src/episignal_backend/ingestion/gdelt/api.py` | GDELT DOC 2.0 HTTP client. |
| `packages/backend/src/episignal_backend/ingestion/gdelt/article.py` | Publisher page fetching and robots.txt. |
| `packages/backend/src/episignal_backend/ingestion/gdelt/connector.py` | `GdeltConnector`. |
| `packages/backend/src/episignal_backend/ingestion/discovery.py` | `run_discovery`. Pure decisions, Protocol-only imports. |
| `packages/backend/src/episignal_backend/discover_runner.py` | Entry point for `pnpm discover:gdelt`. |
| `database/migrations/versions/20260827_0003_gdelt_discovery.py` | Schema revision. |
| `database/seeds/gdelt_queries.json` | The reviewed query library. |

**Modified:**

| Path | Change |
| --- | --- |
| `packages/backend/src/episignal_backend/db/types.py` | Add `DiscoveryMethod`. |
| `packages/backend/src/episignal_backend/models/signal.py` | Add five discovery columns. |
| `packages/backend/src/episignal_backend/models/catalog.py` | Add `Source.domain`. |
| `packages/backend/src/episignal_backend/models/__init__.py` | Export `GdeltQueryRule`. |
| `packages/backend/src/episignal_backend/ingestion/documents.py` | Add the five discovery contracts. |
| `packages/backend/src/episignal_backend/ingestion/protocol.py` | Add two discovery Protocols. |
| `packages/backend/src/episignal_backend/ingestion/repository.py` | Set `first_seen_at`; add `SqlAlchemyDiscoveryRepository`. |
| `packages/backend/src/episignal_backend/seeds.py` | Seed query rules; generalize the natural key. |
| `packages/backend/src/episignal_backend/config.py` | Add the GDELT settings. |
| `apps/api/tests/test_migrations.py` | Assert the new head and the new invariants. |
| `package.json` | Add `discover:gdelt`. |
| `apps/api/.env.example` | Document the GDELT settings. |

---

### Task 1: Add the discovery vocabulary

A signal must record how it was found, separately from who published it. The
default is `direct`, so every existing WHO and ECDC signal keeps its meaning
with no data migration.

**Files:**
- Modify: `packages/backend/src/episignal_backend/db/types.py`
- Test: `packages/backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_models.py`:

```python
def test_discovery_method_stores_lowercase_values() -> None:
    from episignal_backend.db.types import DiscoveryMethod

    assert DiscoveryMethod.DIRECT.value == "direct"
    assert DiscoveryMethod.GDELT.value == "gdelt"
    assert [member.value for member in DiscoveryMethod] == ["direct", "gdelt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_models.py::test_discovery_method_stores_lowercase_values -v`

Expected: FAIL with `ImportError: cannot import name 'DiscoveryMethod'`.

- [ ] **Step 3: Write minimal implementation**

In `packages/backend/src/episignal_backend/db/types.py`, add after the
`CredibilityTier` class:

```python
class DiscoveryMethod(StrEnum):
    DIRECT = "direct"
    GDELT = "gdelt"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_models.py::test_discovery_method_stores_lowercase_values -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/db/types.py packages/backend/tests/test_models.py
git commit -m "feat: add the discovery method vocabulary"
```

---

### Task 2: Map GDELT locale names to codes

GDELT returns `"Spanish"` and `"United States"`, not `es` and `US`. The
`signals.language` column is `String(8)` and `country_code` is `String(2)`, so
an unmapped value truncated to width would become a wrong code indistinguishable
from a right one. Unmapped values must yield `None`.

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/gdelt/__init__.py`
- Create: `packages/backend/src/episignal_backend/ingestion/gdelt/locale.py`
- Test: `packages/backend/tests/test_gdelt_locale.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_gdelt_locale.py`:

```python
import pytest

from episignal_backend.ingestion.gdelt.locale import country_code, language_code


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("English", "en"),
        ("Spanish", "es"),
        ("Vietnamese", "vi"),
        ("Thai", "th"),
        ("  spanish  ", "es"),
        ("SPANISH", "es"),
    ],
)
def test_language_code_maps_known_names(name: str, expected: str) -> None:
    assert language_code(name) == expected


@pytest.mark.parametrize("name", ["", "   ", "Klingon", "Not A Language"])
def test_language_code_returns_none_for_unmapped_names(name: str) -> None:
    assert language_code(name) is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("United States", "US"),
        ("Vietnam", "VN"),
        ("Viet Nam", "VN"),
        ("Thailand", "TH"),
        ("  united states  ", "US"),
    ],
)
def test_country_code_maps_known_names(name: str, expected: str) -> None:
    assert country_code(name) == expected


@pytest.mark.parametrize("name", ["", "   ", "Atlantis"])
def test_country_code_returns_none_for_unmapped_names(name: str) -> None:
    assert country_code(name) is None


def test_every_language_code_fits_the_column() -> None:
    from episignal_backend.ingestion.gdelt.locale import LANGUAGE_CODES

    assert all(len(code) <= 8 for code in LANGUAGE_CODES.values())


def test_every_country_code_fits_the_column() -> None:
    from episignal_backend.ingestion.gdelt.locale import COUNTRY_CODES

    assert all(len(code) == 2 for code in COUNTRY_CODES.values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_gdelt_locale.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ingestion.gdelt'`.

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ingestion/gdelt/__init__.py` as an
empty file.

Create `packages/backend/src/episignal_backend/ingestion/gdelt/locale.py`:

```python
"""GDELT locale names to codes.

The DOC 2.0 API reports `language` and `sourcecountry` as English names, but
`signals.language` is eight characters and `country_code` is two. Truncating a
name to fit would turn "United States" into "Un", a wrong code that reads
exactly like a right one, so an unmapped name yields None and is counted by the
caller instead.

These tables are deliberately incomplete. A run reports how many values it could
not map, which is what tells us which entries to add next.
"""

LANGUAGE_CODES: dict[str, str] = {
    "arabic": "ar",
    "bengali": "bn",
    "burmese": "my",
    "chinese": "zh",
    "czech": "cs",
    "danish": "da",
    "dutch": "nl",
    "english": "en",
    "finnish": "fi",
    "french": "fr",
    "german": "de",
    "greek": "el",
    "hebrew": "he",
    "hindi": "hi",
    "hungarian": "hu",
    "indonesian": "id",
    "italian": "it",
    "japanese": "ja",
    "khmer": "km",
    "korean": "ko",
    "lao": "lo",
    "malay": "ms",
    "nepali": "ne",
    "norwegian": "no",
    "persian": "fa",
    "polish": "pl",
    "portuguese": "pt",
    "romanian": "ro",
    "russian": "ru",
    "sinhala": "si",
    "spanish": "es",
    "swahili": "sw",
    "swedish": "sv",
    "tagalog": "tl",
    "tamil": "ta",
    "telugu": "te",
    "thai": "th",
    "turkish": "tr",
    "ukrainian": "uk",
    "urdu": "ur",
    "vietnamese": "vi",
}

COUNTRY_CODES: dict[str, str] = {
    "afghanistan": "AF",
    "algeria": "DZ",
    "angola": "AO",
    "argentina": "AR",
    "australia": "AU",
    "austria": "AT",
    "bangladesh": "BD",
    "belgium": "BE",
    "benin": "BJ",
    "bolivia": "BO",
    "brazil": "BR",
    "burkina faso": "BF",
    "burundi": "BI",
    "cambodia": "KH",
    "cameroon": "CM",
    "canada": "CA",
    "chad": "TD",
    "chile": "CL",
    "china": "CN",
    "colombia": "CO",
    "congo": "CG",
    "democratic republic of the congo": "CD",
    "ecuador": "EC",
    "egypt": "EG",
    "ethiopia": "ET",
    "france": "FR",
    "germany": "DE",
    "ghana": "GH",
    "guinea": "GN",
    "haiti": "HT",
    "india": "IN",
    "indonesia": "ID",
    "iran": "IR",
    "iraq": "IQ",
    "italy": "IT",
    "japan": "JP",
    "kenya": "KE",
    "laos": "LA",
    "lebanon": "LB",
    "liberia": "LR",
    "madagascar": "MG",
    "malawi": "MW",
    "malaysia": "MY",
    "mali": "ML",
    "mexico": "MX",
    "morocco": "MA",
    "mozambique": "MZ",
    "myanmar": "MM",
    "nepal": "NP",
    "netherlands": "NL",
    "niger": "NE",
    "nigeria": "NG",
    "pakistan": "PK",
    "peru": "PE",
    "philippines": "PH",
    "poland": "PL",
    "russia": "RU",
    "rwanda": "RW",
    "saudi arabia": "SA",
    "senegal": "SN",
    "sierra leone": "SL",
    "singapore": "SG",
    "somalia": "SO",
    "south africa": "ZA",
    "south korea": "KR",
    "south sudan": "SS",
    "spain": "ES",
    "sri lanka": "LK",
    "sudan": "SD",
    "sweden": "SE",
    "switzerland": "CH",
    "syria": "SY",
    "taiwan": "TW",
    "tanzania": "TZ",
    "thailand": "TH",
    "togo": "TG",
    "tunisia": "TN",
    "turkey": "TR",
    "uganda": "UG",
    "ukraine": "UA",
    "united arab emirates": "AE",
    "united kingdom": "GB",
    "united states": "US",
    "uruguay": "UY",
    "venezuela": "VE",
    "viet nam": "VN",
    "vietnam": "VN",
    "yemen": "YE",
    "zambia": "ZM",
    "zimbabwe": "ZW",
}


def _key(value: str) -> str:
    return " ".join(value.split()).casefold()


def language_code(name: str) -> str | None:
    return LANGUAGE_CODES.get(_key(name))


def country_code(name: str) -> str | None:
    return COUNTRY_CODES.get(_key(name))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_gdelt_locale.py -v`

Expected: PASS, 16 tests.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/gdelt packages/backend/tests/test_gdelt_locale.py
git commit -m "feat: map GDELT locale names to codes"
```

---

### Task 3: Add the query rule model

The query library lives in the database so it can be edited without a
deployment, and is seeded from JSON so what the radar watches stays reviewable
in Git.

`language` is not null with the sentinel `any`. PostgreSQL treats NULLs as
distinct in a unique constraint, so a nullable column would let the same
unrestricted query be seeded without limit.

**Files:**
- Create: `packages/backend/src/episignal_backend/models/discovery.py`
- Modify: `packages/backend/src/episignal_backend/models/__init__.py`
- Test: `packages/backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

`packages/backend/tests/test_models.py` asserts set-equality on the table names,
so it fails the moment a table is added. Update `EXPECTED_TABLES` at the top of
that file first:

```python
EXPECTED_TABLES = {
    "sources",
    "signals",
    "diseases",
    "pathogens",
    "events",
    "event_signals",
    "event_observations",
    "event_locations",
    "gdelt_query_rules",
}
```

Then append to the same file:

```python
def test_gdelt_query_rule_table_shape() -> None:
    from episignal_backend.models import GdeltQueryRule

    table = GdeltQueryRule.__table__
    assert table.name == "gdelt_query_rules"
    assert not table.c.rule_group.nullable
    assert not table.c.query.nullable
    assert not table.c.label.nullable
    assert not table.c.language.nullable
    assert not table.c.active.nullable
    constraint_columns = {
        tuple(sorted(column.name for column in constraint.columns))
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("language", "query") in constraint_columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_models.py::test_gdelt_query_rule_table_shape -v`

Expected: FAIL with `ImportError: cannot import name 'GdeltQueryRule'`.

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/models/discovery.py`:

```python
from sqlalchemy import Boolean, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin, TimestampMixin

ANY_LANGUAGE = "any"


class GdeltQueryRule(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "gdelt_query_rules"
    __table_args__ = (UniqueConstraint("query", "language", name="uq_gdelt_query_rules_query"),)

    rule_group: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # Not nullable: PostgreSQL treats NULLs as distinct, so a nullable column
    # would let the same unrestricted query be seeded without limit.
    language: Mapped[str] = mapped_column(
        Text, nullable=False, default=ANY_LANGUAGE, server_default=ANY_LANGUAGE
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
```

Replace `packages/backend/src/episignal_backend/models/__init__.py` with:

```python
from episignal_backend.models.catalog import Disease, Pathogen, Source
from episignal_backend.models.discovery import GdeltQueryRule
from episignal_backend.models.event import (
    Event,
    EventLocation,
    EventObservation,
    EventSignal,
)
from episignal_backend.models.signal import Signal

__all__ = [
    "Disease",
    "Event",
    "EventLocation",
    "EventObservation",
    "EventSignal",
    "GdeltQueryRule",
    "Pathogen",
    "Signal",
    "Source",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_models.py -v`

Expected: PASS, all tests including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/models packages/backend/tests/test_models.py
git commit -m "feat: add the GDELT query rule model"
```

---

### Task 4: Add the discovery columns to signals and sources

`first_seen_at` is not `created_at`. A revised article is stored as a new signal
version with a new `created_at`, but `first_seen_at` records when EpiSignal
first saw that URL in any version. The detection-lead-time metric depends on
that distinction.

`published_at_offset_minutes` exists because `timestamptz` normalizes to UTC and
discards the offset the publisher wrote. "07:42 ICT" cannot be reconstructed
from a UTC instant alone.

**Files:**
- Modify: `packages/backend/src/episignal_backend/models/signal.py`
- Modify: `packages/backend/src/episignal_backend/models/catalog.py`
- Modify: `packages/backend/src/episignal_backend/ingestion/repository.py`
- Test: `packages/backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_models.py`:

```python
def test_signal_records_discovery_provenance() -> None:
    from episignal_backend.models import Signal

    columns = Signal.__table__.c
    assert not columns.discovered_via.nullable
    assert not columns.first_seen_at.nullable
    assert columns.gdelt_seen_at.nullable
    assert columns.published_at_offset_minutes.nullable
    assert columns.query_rule_id.nullable


def test_source_records_its_domain() -> None:
    from episignal_backend.models import Source

    assert Source.__table__.c.domain.nullable
    assert Source.__table__.c.domain.unique
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_models.py::test_signal_records_discovery_provenance -v`

Expected: FAIL with `AttributeError` on `discovered_via`.

- [ ] **Step 3: Write minimal implementation**

In `packages/backend/src/episignal_backend/models/signal.py`, extend the imports:

```python
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
)
```

Add `DiscoveryMethod` to the `db.types` import:

```python
from episignal_backend.db.types import DiscoveryMethod, ProcessingStatus, SignalType, vocabulary
```

Add these two indexes to `__table_args__`, after `Index("ix_signals_processing_status", "processing_status")`:

```python
        Index("ix_signals_discovered_via", "discovered_via"),
        Index("ix_signals_first_seen_at", "first_seen_at"),
```

Add these five columns at the end of the `Signal` class body:

```python
    discovered_via: Mapped[DiscoveryMethod] = mapped_column(
        vocabulary(DiscoveryMethod, "discovery_method_values"),
        nullable=False,
        default=DiscoveryMethod.DIRECT,
        server_default=DiscoveryMethod.DIRECT.value,
    )
    # Distinct from created_at: a revision is stored as a new row with a new
    # created_at, but first_seen_at must survive that or detection lead time
    # measures the revision rather than the discovery.
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gdelt_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # timestamptz normalizes to UTC and discards the offset the publisher wrote,
    # which is a property of the document, not of the reader.
    published_at_offset_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    query_rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("gdelt_query_rules.id", ondelete="SET NULL")
    )
```

In `packages/backend/src/episignal_backend/models/catalog.py`, add to the
`Source` class body, after `feed_url`:

```python
    domain: Mapped[str | None] = mapped_column(Text, unique=True)
```

In `packages/backend/src/episignal_backend/ingestion/repository.py`, add
`first_seen_at` to `build_signal` so official ingestion keeps working:

```python
def build_signal(signal: NormalizedSignal, source_id: UUID) -> Signal:
    return Signal(
        source_id=source_id,
        external_id=signal.external_id,
        url=signal.url,
        canonical_url=signal.canonical_url,
        title=signal.title,
        raw_text=signal.raw_text,
        published_at=signal.published_at,
        retrieved_at=signal.retrieved_at,
        # An official document's first sighting is the retrieval that produced
        # this version; there is no earlier discovery step to inherit from.
        first_seen_at=signal.retrieved_at,
        language=signal.language,
        content_hash=signal.content_hash,
        signal_type=signal.signal_type,
        processing_status=signal.processing_status,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests -v`

Expected: PASS. Every existing ingestion test still passes.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/models packages/backend/src/episignal_backend/ingestion/repository.py packages/backend/tests/test_models.py
git commit -m "feat: record discovery provenance on signals and sources"
```

---

### Task 5: Write the schema migration

**Files:**
- Create: `database/migrations/versions/20260827_0003_gdelt_discovery.py`
- Modify: `apps/api/tests/test_migrations.py`
- Test: `apps/api/tests/test_migrations.py`

- [ ] **Step 1: Write the failing test**

In `apps/api/tests/test_migrations.py`, change the head assertion:

```python
def test_migrations_have_one_linear_head() -> None:
    root = Path(__file__).parents[3]
    config = Config(root / "database" / "alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20260827_0003"]
```

Append:

```python
def test_third_revision_adds_gdelt_discovery() -> None:
    sql = render_offline("upgrade", "head")
    assert "create table gdelt_query_rules" in sql
    assert "uq_gdelt_query_rules_query" in sql
    assert "discovery_method_values" in sql
    assert "ix_signals_discovered_via" in sql
    assert "ix_signals_first_seen_at" in sql
    assert "uq_sources_domain" in sql
    for column in (
        "discovered_via",
        "first_seen_at",
        "gdelt_seen_at",
        "published_at_offset_minutes",
        "query_rule_id",
    ):
        assert f"add column {column}" in sql


def test_third_revision_backfills_first_seen_at_before_enforcing_it() -> None:
    sql = render_offline("upgrade", "head")
    # The column is added nullable, filled from retrieved_at, and only then made
    # NOT NULL. Reordering these would fail on any database holding signals.
    assert sql.index("set first_seen_at = retrieved_at") < sql.index(
        "alter column first_seen_at set not null"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_migrations.py -v`

Expected: FAIL — the head is still `20260826_0002`.

- [ ] **Step 3: Write minimal implementation**

Create `database/migrations/versions/20260827_0003_gdelt_discovery.py`:

```python
"""add GDELT discovery provenance

Revision ID: 20260827_0003
Revises: 20260826_0002
Create Date: 2026-08-27

GDELT discovers an article; the publisher wrote it. Recording the two separately
is what keeps a local newspaper from being labelled as its discovery mechanism.
The added timestamps stay distinct because detection lead time is the difference
between them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0003"
down_revision: str | None = "20260826_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DISCOVERY_METHODS = ("direct", "gdelt")


def upgrade() -> None:
    op.create_table(
        "gdelt_query_rules",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("rule_group", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), server_default="any", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_gdelt_query_rules"),
        sa.UniqueConstraint("query", "language", name="uq_gdelt_query_rules_query"),
    )

    op.add_column("sources", sa.Column("domain", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_sources_domain", "sources", ["domain"])

    op.add_column(
        "signals",
        sa.Column(
            "discovered_via",
            sa.Enum(
                *DISCOVERY_METHODS,
                name="discovery_method_values",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="direct",
            nullable=False,
        ),
    )
    # Added nullable, backfilled, then constrained. Adding it NOT NULL outright
    # would fail on any database that already holds signals.
    op.add_column("signals", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE signals SET first_seen_at = retrieved_at WHERE first_seen_at IS NULL")
    op.alter_column("signals", "first_seen_at", nullable=False)

    op.add_column("signals", sa.Column("gdelt_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "signals", sa.Column("published_at_offset_minutes", sa.SmallInteger(), nullable=True)
    )
    op.add_column("signals", sa.Column("query_rule_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_signals_query_rule_id_gdelt_query_rules",
        "signals",
        "gdelt_query_rules",
        ["query_rule_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_signals_discovered_via", "signals", ["discovered_via"])
    op.create_index("ix_signals_first_seen_at", "signals", ["first_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_signals_first_seen_at", table_name="signals")
    op.drop_index("ix_signals_discovered_via", table_name="signals")
    op.drop_constraint("fk_signals_query_rule_id_gdelt_query_rules", "signals", type_="foreignkey")
    op.drop_column("signals", "query_rule_id")
    op.drop_column("signals", "published_at_offset_minutes")
    op.drop_column("signals", "gdelt_seen_at")
    op.drop_column("signals", "first_seen_at")
    op.drop_constraint("ck_signals_discovery_method_values", "signals", type_="check")
    op.drop_column("signals", "discovered_via")
    op.drop_constraint("uq_sources_domain", "sources", type_="unique")
    op.drop_column("sources", "domain")
    op.drop_table("gdelt_query_rules")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/api/tests/test_migrations.py -v`

Expected: PASS.

If `test_third_revision_backfills_first_seen_at_before_enforcing_it` fails
because the rendered SQL casing differs, note that `render_offline` lowercases
its output; check the actual rendered text with
`uv run python -m alembic -c database/alembic.ini upgrade head --sql` before
changing the assertion.

- [ ] **Step 5: Verify the schema check still agrees**

Run: `uv run pytest packages/backend/tests/test_schema_check.py -v`

Expected: PASS. If it fails, the model and the migration disagree — fix the
migration, not the test.

- [ ] **Step 6: Commit**

```bash
git add database/migrations/versions/20260827_0003_gdelt_discovery.py apps/api/tests/test_migrations.py
git commit -m "feat: migrate the schema for GDELT discovery"
```

---

### Task 6: Seed the query library

The query library is grouped by epidemiological signal type, never a single
generic `outbreak` query.

**Files:**
- Create: `database/seeds/gdelt_queries.json`
- Modify: `packages/backend/src/episignal_backend/seeds.py`
- Modify: `packages/backend/src/episignal_backend/seed_runner.py`
- Test: `packages/backend/tests/test_seeds.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_seeds.py`:

```python
def test_query_rules_load_and_are_grouped() -> None:
    from episignal_backend.seeds import load_query_rules

    rules = load_query_rules()
    assert len(rules) >= 40
    groups = {rule.rule_group for rule in rules}
    assert groups == {
        "known_disease",
        "syndromic",
        "zoonotic",
        "public_health_abnormality",
    }


def test_query_rules_have_no_duplicate_identity() -> None:
    from episignal_backend.seeds import load_query_rules

    rules = load_query_rules()
    identities = [(rule.query, rule.language) for rule in rules]
    assert len(identities) == len(set(identities))


def test_no_query_rule_is_a_bare_generic_term() -> None:
    from episignal_backend.seeds import load_query_rules

    # A single generic query returns mostly noise and defeats grouping.
    banned = {"outbreak", "disease", "virus", "illness"}
    assert all(rule.query.strip().casefold() not in banned for rule in load_query_rules())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_seeds.py -v`

Expected: FAIL with `ImportError: cannot import name 'load_query_rules'`.

- [ ] **Step 3: Create the seed file**

Create `database/seeds/gdelt_queries.json`. Every entry uses
`"language": "any"`; language-restricted rules are added once the `sourcelang:`
operator is verified in Task 16.

```json
[
  { "rule_group": "known_disease", "query": "cholera", "label": "Cholera" },
  { "rule_group": "known_disease", "query": "dengue", "label": "Dengue" },
  { "rule_group": "known_disease", "query": "measles", "label": "Measles" },
  { "rule_group": "known_disease", "query": "mpox", "label": "Mpox" },
  { "rule_group": "known_disease", "query": "H5N1", "label": "H5N1" },
  { "rule_group": "known_disease", "query": "\"avian influenza\"", "label": "Avian influenza" },
  { "rule_group": "known_disease", "query": "Ebola", "label": "Ebola" },
  { "rule_group": "known_disease", "query": "Marburg", "label": "Marburg" },
  { "rule_group": "known_disease", "query": "\"Lassa fever\"", "label": "Lassa fever" },
  { "rule_group": "known_disease", "query": "\"yellow fever\"", "label": "Yellow fever" },
  { "rule_group": "known_disease", "query": "\"West Nile virus\"", "label": "West Nile virus" },
  { "rule_group": "known_disease", "query": "chikungunya", "label": "Chikungunya" },
  { "rule_group": "known_disease", "query": "diphtheria", "label": "Diphtheria" },
  { "rule_group": "known_disease", "query": "pertussis", "label": "Pertussis" },
  { "rule_group": "known_disease", "query": "meningitis", "label": "Meningitis" },
  { "rule_group": "known_disease", "query": "polio", "label": "Polio" },
  { "rule_group": "known_disease", "query": "anthrax", "label": "Anthrax" },
  { "rule_group": "known_disease", "query": "hantavirus", "label": "Hantavirus" },
  { "rule_group": "known_disease", "query": "leptospirosis", "label": "Leptospirosis" },
  { "rule_group": "known_disease", "query": "rabies", "label": "Rabies" },
  { "rule_group": "known_disease", "query": "malaria", "label": "Malaria" },
  { "rule_group": "known_disease", "query": "Zika", "label": "Zika" },
  { "rule_group": "known_disease", "query": "typhoid", "label": "Typhoid" },
  { "rule_group": "known_disease", "query": "salmonella", "label": "Salmonella" },
  { "rule_group": "known_disease", "query": "MERS", "label": "MERS" },
  { "rule_group": "syndromic", "query": "\"unknown illness\"", "label": "Unknown illness" },
  { "rule_group": "syndromic", "query": "\"mysterious illness\"", "label": "Mysterious illness" },
  { "rule_group": "syndromic", "query": "\"unexplained illness\"", "label": "Unexplained illness" },
  { "rule_group": "syndromic", "query": "\"unknown disease\"", "label": "Unknown disease" },
  { "rule_group": "syndromic", "query": "\"unknown fever\"", "label": "Unknown fever" },
  { "rule_group": "syndromic", "query": "\"mysterious fever\"", "label": "Mysterious fever" },
  { "rule_group": "syndromic", "query": "\"acute febrile illness\"", "label": "Acute febrile illness" },
  { "rule_group": "syndromic", "query": "\"acute watery diarrhea\"", "label": "Acute watery diarrhoea" },
  { "rule_group": "syndromic", "query": "\"bloody diarrhea\"", "label": "Bloody diarrhoea" },
  { "rule_group": "syndromic", "query": "\"severe diarrhea\"", "label": "Severe diarrhoea" },
  { "rule_group": "syndromic", "query": "\"severe pneumonia\"", "label": "Severe pneumonia" },
  { "rule_group": "syndromic", "query": "\"unknown pneumonia\"", "label": "Unknown pneumonia" },
  { "rule_group": "syndromic", "query": "\"respiratory cluster\"", "label": "Respiratory cluster" },
  { "rule_group": "syndromic", "query": "\"unexplained deaths\"", "label": "Unexplained deaths" },
  { "rule_group": "syndromic", "query": "\"mass illness\"", "label": "Mass illness" },
  { "rule_group": "syndromic", "query": "\"students hospitalized\"", "label": "Students hospitalised" },
  { "rule_group": "syndromic", "query": "\"children hospitalized\"", "label": "Children hospitalised" },
  { "rule_group": "syndromic", "query": "\"hospitalized after meal\"", "label": "Hospitalised after a meal" },
  { "rule_group": "zoonotic", "query": "\"mass bird deaths\"", "label": "Mass bird deaths" },
  { "rule_group": "zoonotic", "query": "\"dead wild birds\"", "label": "Dead wild birds" },
  { "rule_group": "zoonotic", "query": "\"poultry deaths\"", "label": "Poultry deaths" },
  { "rule_group": "zoonotic", "query": "\"animal die-off\"", "label": "Animal die-off" },
  { "rule_group": "zoonotic", "query": "\"unusual animal deaths\"", "label": "Unusual animal deaths" },
  { "rule_group": "zoonotic", "query": "\"livestock deaths\"", "label": "Livestock deaths" },
  { "rule_group": "zoonotic", "query": "\"zoonotic infection\"", "label": "Zoonotic infection" },
  { "rule_group": "public_health_abnormality", "query": "\"hospital overwhelmed\"", "label": "Hospital overwhelmed" },
  { "rule_group": "public_health_abnormality", "query": "\"cluster of cases\"", "label": "Cluster of cases" },
  { "rule_group": "public_health_abnormality", "query": "\"unusual cluster\"", "label": "Unusual cluster" },
  { "rule_group": "public_health_abnormality", "query": "\"mass absenteeism\"", "label": "Mass absenteeism" },
  { "rule_group": "public_health_abnormality", "query": "\"unexplained neurological illness\"", "label": "Unexplained neurological illness" },
  { "rule_group": "public_health_abnormality", "query": "\"hemorrhagic illness\"", "label": "Haemorrhagic illness" }
]
```

- [ ] **Step 4: Wire the seed loader**

In `packages/backend/src/episignal_backend/seeds.py`, add to the imports:

```python
from episignal_backend.models import Disease, GdeltQueryRule, Source
from episignal_backend.models.discovery import ANY_LANGUAGE
```

Add the seed model after `SourceSeed`:

```python
class QueryRuleSeed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_group: str = Field(min_length=1)
    query: str = Field(min_length=1)
    label: str = Field(min_length=1)
    language: str = ANY_LANGUAGE
    active: bool = True
```

Replace `SeedResult` and add the loader:

```python
@dataclass(frozen=True)
class SeedResult:
    diseases: int
    sources: int
    query_rules: int


def load_query_rules() -> tuple[QueryRuleSeed, ...]:
    return tuple(
        TypeAdapter(list[QueryRuleSeed]).validate_python(_read_seed("gdelt_queries.json"))
    )
```

Generalize `_upsert` to a composite natural key:

```python
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
```

Replace `seed_database`:

```python
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
```

In `packages/backend/src/episignal_backend/seed_runner.py`, update the print:

```python
    print(
        f"diseases={result.diseases} sources={result.sources} "
        f"query_rules={result.query_rules}"
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_seeds.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add database/seeds/gdelt_queries.json packages/backend/src/episignal_backend/seeds.py packages/backend/src/episignal_backend/seed_runner.py packages/backend/tests/test_seeds.py
git commit -m "feat: seed the GDELT query library"
```

---

### Task 7: Define the discovery contracts

These are the values passed between the connector, the pipeline, and the
repository. They mirror `RawDocument` and `NormalizedSignal`: frozen, validated
at the boundary, and rejecting naive timestamps.

**Files:**
- Modify: `packages/backend/src/episignal_backend/ingestion/documents.py`
- Test: `packages/backend/tests/test_discovery_documents.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_discovery_documents.py`:

```python
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from episignal_backend.db.types import ProcessingStatus
from episignal_backend.ingestion.documents import (
    DiscoveredArticle,
    DiscoveredSignal,
    Publisher,
    QueryRule,
    TimeWindow,
)

SEEN = datetime(2026, 8, 26, 7, 45, tzinfo=UTC)
ICT = timezone(timedelta(hours=7))


def article(**overrides: object) -> DiscoveredArticle:
    values: dict[str, object] = {
        "url": "https://example.vn/a",
        "canonical_url": "https://example.vn/a",
        "title": "Eighteen students hospitalised",
        "domain": "example.vn",
        "gdelt_seen_at": SEEN,
        "language": "vi",
        "country_code": "VN",
    }
    return DiscoveredArticle(**(values | overrides))  # type: ignore[arg-type]


def test_article_rejects_a_naive_seen_time() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        article(gdelt_seen_at=datetime(2026, 8, 26, 7, 45))


def test_article_lowercases_its_domain() -> None:
    assert article(domain="Example.VN").domain == "example.vn"


def test_article_rejects_a_blank_domain() -> None:
    with pytest.raises(ValidationError):
        article(domain="   ")


def test_signal_may_carry_no_body_and_no_publication_time() -> None:
    signal = DiscoveredSignal(
        url="https://example.vn/a",
        canonical_url="https://example.vn/a",
        title="Eighteen students hospitalised",
        raw_text=None,
        published_at=None,
        published_at_offset_minutes=None,
        retrieved_at=SEEN,
        first_seen_at=SEEN,
        gdelt_seen_at=SEEN,
        language="vi",
        content_hash="a" * 64,
        publisher=Publisher(domain="example.vn", name="Example", language="vi", country_code="VN"),
        processing_status=ProcessingStatus.NEEDS_REVIEW,
    )
    assert signal.raw_text is None
    assert signal.published_at is None


def test_signal_preserves_the_publisher_offset() -> None:
    signal = DiscoveredSignal(
        url="https://example.vn/a",
        canonical_url="https://example.vn/a",
        title="Eighteen students hospitalised",
        raw_text="Eighteen students were admitted.",
        published_at=datetime(2026, 8, 26, 7, 42, tzinfo=ICT),
        published_at_offset_minutes=420,
        retrieved_at=SEEN,
        first_seen_at=SEEN,
        gdelt_seen_at=SEEN,
        language="vi",
        content_hash="b" * 64,
        publisher=Publisher(domain="example.vn", name="Example", language="vi", country_code="VN"),
    )
    assert signal.published_at_offset_minutes == 420


def test_query_rule_and_window_are_frozen() -> None:
    rule = QueryRule(id=None, rule_group="syndromic", query='"unknown fever"', label="Unknown fever")
    window = TimeWindow(start=SEEN, end=SEEN)
    with pytest.raises(ValidationError):
        rule.query = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        window.start = SEEN  # type: ignore[misc]


def test_window_rejects_an_end_before_its_start() -> None:
    with pytest.raises(ValidationError, match="end"):
        TimeWindow(start=SEEN, end=SEEN - timedelta(minutes=1))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_discovery_documents.py -v`

Expected: FAIL with `ImportError: cannot import name 'DiscoveredArticle'`.

- [ ] **Step 3: Write minimal implementation**

Append to `packages/backend/src/episignal_backend/ingestion/documents.py`. Add
`UUID` and `model_validator` to the imports at the top of the file:

```python
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
```

Then append:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_discovery_documents.py -v`

Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/documents.py packages/backend/tests/test_discovery_documents.py
git commit -m "feat: define the discovery contracts"
```

---

### Task 8: Define the discovery boundaries

**Files:**
- Modify: `packages/backend/src/episignal_backend/ingestion/protocol.py`
- Test: `packages/backend/tests/test_discovery_protocol.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_discovery_protocol.py`:

```python
from episignal_backend.ingestion.protocol import DiscoveryConnector, DiscoveryRepository


def test_discovery_protocols_are_runtime_checkable() -> None:
    class NotAConnector:
        pass

    assert not isinstance(NotAConnector(), DiscoveryConnector)
    assert not isinstance(NotAConnector(), DiscoveryRepository)


def test_retrieval_failed_is_distinct_from_unsupported() -> None:
    from episignal_backend.ingestion.protocol import RetrievalFailed, UnsupportedDocument

    assert not issubclass(RetrievalFailed, UnsupportedDocument)
    assert issubclass(RetrievalFailed, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_discovery_protocol.py -v`

Expected: FAIL with `ImportError: cannot import name 'DiscoveryConnector'`.

- [ ] **Step 3: Write minimal implementation**

Append to `packages/backend/src/episignal_backend/ingestion/protocol.py`. Extend
the imports at the top of the file:

```python
from episignal_backend.ingestion.documents import (
    DiscoveredArticle,
    DiscoveredSignal,
    NormalizedSignal,
    Publisher,
    QueryRule,
    RawDocument,
    TimeWindow,
)
```

Then append:

```python
@runtime_checkable
class DiscoveryConnector(Protocol):
    """A radar: it finds articles other people published.

    Distinct from `SourceConnector`, which speaks for exactly one known
    publisher. `discover` returns metadata only and opens no publisher
    connection, so the pipeline can drop already-seen URLs before paying for a
    page fetch.
    """

    discovery_name: str

    def discover(
        self, rule: QueryRule, window: TimeWindow
    ) -> Sequence[DiscoveredArticle]: ...

    def retrieve(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal: ...

    def stub(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal: ...


@runtime_checkable
class DiscoveryRepository(Protocol):
    def active_rules(self) -> Sequence[QueryRule]: ...

    def seen_urls(self, canonical_urls: Sequence[str]) -> frozenset[str]: ...

    def first_seen_at(self, canonical_url: str) -> datetime | None: ...

    def publisher_source_id(self, publisher: Publisher) -> UUID: ...

    def add(self, signal: DiscoveredSignal, source_id: UUID) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class RetrievalFailed(Exception):
    """The publisher's page could not be turned into evidence.

    Distinct from `UnsupportedDocument`: the article is wanted, and the
    discovery is kept as a stub for retry, rather than rejected outright.
    """
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_discovery_protocol.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/protocol.py packages/backend/tests/test_discovery_protocol.py
git commit -m "feat: define the discovery boundaries"
```

---

### Task 9: Extract publication time, title, and body from a publisher page

This is the module that makes the whole slice possible: GDELT supplies neither a
publication time nor any article text, so both come from here. It is a pure
function of an HTML string and is tested entirely against committed fixtures.

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/gdelt/extract.py`
- Create: `packages/backend/tests/fixtures/article_og_time.html`
- Create: `packages/backend/tests/fixtures/article_jsonld.html`
- Create: `packages/backend/tests/fixtures/article_time_tag.html`
- Create: `packages/backend/tests/fixtures/article_no_date.html`
- Create: `packages/backend/tests/fixtures/article_no_body.html`
- Test: `packages/backend/tests/test_gdelt_extract.py`

- [ ] **Step 1: Create the fixtures**

`packages/backend/tests/fixtures/article_og_time.html`:

```html
<html>
  <head>
    <meta property="og:title" content="18 students hospitalised after unexplained illness" />
    <meta property="og:site_name" content="Example News Vietnam" />
    <meta property="article:published_time" content="2026-08-26T07:42:00+07:00" />
  </head>
  <body>
    <nav><p>Home</p></nav>
    <article>
      <p>Eighteen students were admitted to hospital on Tuesday.</p>
      <p>Health officials said the cause is not yet known.</p>
    </article>
    <footer><p>Copyright Example News</p></footer>
  </body>
</html>
```

`packages/backend/tests/fixtures/article_jsonld.html`:

```html
<html>
  <head>
    <title>Cholera cases rise in the delta</title>
    <script type="application/ld+json">
      { "@type": "NewsArticle", "datePublished": "2026-08-25T18:30:00Z" }
    </script>
  </head>
  <body>
    <p>Provincial authorities reported 42 new cholera cases this week.</p>
  </body>
</html>
```

`packages/backend/tests/fixtures/article_time_tag.html`:

```html
<html>
  <head><title>Poultry deaths reported</title></head>
  <body>
    <time datetime="2026-08-24T09:15:00+02:00">24 August</time>
    <p>Farmers reported the sudden death of several hundred birds.</p>
  </body>
</html>
```

`packages/backend/tests/fixtures/article_no_date.html`:

```html
<html>
  <head><title>Unusual cluster under investigation</title></head>
  <body>
    <p>Investigators are examining a cluster of eleven cases.</p>
  </body>
</html>
```

`packages/backend/tests/fixtures/article_no_body.html`:

```html
<html>
  <head><title>Subscribe to continue</title></head>
  <body>
    <div><span>Subscribe</span></div>
  </body>
</html>
```

- [ ] **Step 2: Write the failing test**

Create `packages/backend/tests/test_gdelt_extract.py`:

```python
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from episignal_backend.ingestion.gdelt.extract import extract_page, parse_timestamp

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_reads_the_open_graph_publication_time_and_offset() -> None:
    page = extract_page(fixture("article_og_time.html"))
    assert page.published_at == datetime(
        2026, 8, 26, 7, 42, tzinfo=timezone(timedelta(hours=7))
    )
    assert page.published_at_offset_minutes == 420


def test_prefers_the_open_graph_title_over_the_document_title() -> None:
    page = extract_page(fixture("article_og_time.html"))
    assert page.title == "18 students hospitalised after unexplained illness"
    assert page.site_name == "Example News Vietnam"


def test_excludes_navigation_and_footer_from_the_body() -> None:
    page = extract_page(fixture("article_og_time.html"))
    assert "Eighteen students were admitted" in page.body
    assert "Home" not in page.body
    assert "Copyright" not in page.body


def test_reads_json_ld_date_published() -> None:
    page = extract_page(fixture("article_jsonld.html"))
    assert page.published_at == datetime(2026, 8, 25, 18, 30, tzinfo=timezone.utc)
    assert page.published_at_offset_minutes == 0
    assert page.title == "Cholera cases rise in the delta"


def test_reads_a_time_element_datetime() -> None:
    page = extract_page(fixture("article_time_tag.html"))
    assert page.published_at == datetime(
        2026, 8, 24, 9, 15, tzinfo=timezone(timedelta(hours=2))
    )
    assert page.published_at_offset_minutes == 120


def test_a_page_without_a_date_still_yields_a_body() -> None:
    page = extract_page(fixture("article_no_date.html"))
    assert page.published_at is None
    assert page.published_at_offset_minutes is None
    assert "eleven cases" in page.body


def test_a_page_without_prose_yields_an_empty_body() -> None:
    page = extract_page(fixture("article_no_body.html"))
    assert page.body == ""


@pytest.mark.parametrize(
    ("value", "expected_offset"),
    [
        ("2026-08-26T07:42:00+07:00", 420),
        ("2026-08-25T18:30:00Z", 0),
        ("2026-08-25T18:30:00+00:00", 0),
        ("2026-08-24T09:15:00-05:00", -300),
    ],
)
def test_parse_timestamp_preserves_the_stated_offset(value: str, expected_offset: int) -> None:
    parsed = parse_timestamp(value)
    assert parsed is not None
    assert parsed[1] == expected_offset


def test_parse_timestamp_returns_no_offset_for_a_bare_date() -> None:
    parsed = parse_timestamp("2026-08-24")
    assert parsed is not None
    # A date with no time zone states a day, not an instant. Inventing an offset
    # would fabricate precision the publisher did not give.
    assert parsed[1] is None


@pytest.mark.parametrize("value", ["", "   ", "not a date", "26/08/2026"])
def test_parse_timestamp_rejects_unparseable_values(value: str) -> None:
    assert parse_timestamp(value) is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_gdelt_extract.py -v`

Expected: FAIL with `ModuleNotFoundError` for `extract`.

- [ ] **Step 4: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ingestion/gdelt/extract.py`:

```python
"""Turning a publisher's page into evidence.

GDELT reports that an article exists; it reports neither when the article was
published nor what it says. Both come from the publisher's own markup, which is
why this module exists and why it is pure: every branch below is reachable from
a committed fixture with no network access.

Parsing uses the standard library, matching `ingestion/html_text.py`. A news
page is not trusted markup, and `HTMLParser` tolerates the malformed tag soup
real publishers serve.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser

BODY_TAGS = frozenset({"p"})
EXCLUDED_TAGS = frozenset({"script", "style", "nav", "header", "footer", "aside", "form"})
DATE_META_PROPERTIES = (
    "article:published_time",
    "og:article:published_time",
    "datepublished",
    "date",
    "pubdate",
    "publish-date",
    "dc.date.issued",
)
JSON_LD_DATE_KEYS = ("datePublished", "dateCreated")


@dataclass(frozen=True)
class PageMetadata:
    title: str | None
    site_name: str | None
    published_at: datetime | None
    published_at_offset_minutes: int | None
    body: str


def parse_timestamp(value: str) -> tuple[datetime, int | None] | None:
    """Parse an ISO 8601 value, keeping the offset the publisher stated.

    The offset is returned separately because `timestamptz` normalizes to UTC
    and discards it, and the publication time a reader should see is the one the
    publisher wrote. A bare date yields no offset rather than a guessed one.
    """
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC), None
    offset = parsed.utcoffset()
    return parsed, None if offset is None else int(offset.total_seconds() // 60)


def _json_ld_dates(payload: object) -> list[str]:
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in JSON_LD_DATE_KEYS and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_json_ld_dates(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(_json_ld_dates(item))
    return found


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og_title: str | None = None
        self.site_name: str | None = None
        self.document_title: str | None = None
        self.date_candidates: list[str] = []
        self.body_parts: list[str] = []
        self._excluded = 0
        self._in_body_tag = 0
        self._in_document_title = False
        self._in_json_ld = False
        self._json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): (value or "") for name, value in attrs}

        if tag == "script" and attributes.get("type", "").lower() == "application/ld+json":
            self._in_json_ld = True
            return
        if tag in EXCLUDED_TAGS:
            self._excluded += 1
            return
        if self._excluded:
            return

        if tag == "meta":
            self._read_meta(attributes)
        elif tag == "time":
            stated = attributes.get("datetime", "")
            if stated:
                self.date_candidates.append(stated)
        elif tag == "title":
            self._in_document_title = True
        elif tag in BODY_TAGS:
            self._in_body_tag += 1
            self.body_parts.append(" ")

    def _read_meta(self, attributes: dict[str, str]) -> None:
        key = (attributes.get("property") or attributes.get("name") or "").lower()
        content = attributes.get("content", "")
        if not content:
            return
        if key == "og:title":
            self.og_title = content
        elif key == "og:site_name":
            self.site_name = content
        elif key in DATE_META_PROPERTIES:
            self.date_candidates.append(content)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_json_ld:
            self._in_json_ld = False
            self._read_json_ld("".join(self._json_ld_parts))
            self._json_ld_parts = []
            return
        if tag in EXCLUDED_TAGS:
            if self._excluded:
                self._excluded -= 1
            return
        if tag == "title":
            self._in_document_title = False
        elif tag in BODY_TAGS and self._in_body_tag:
            self._in_body_tag -= 1
            self.body_parts.append(" ")

    def _read_json_ld(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Publishers ship broken JSON-LD often enough that it must not stop
            # the rest of the page from being read.
            return
        self.date_candidates.extend(_json_ld_dates(payload))

    def handle_data(self, data: str) -> None:
        if self._in_json_ld:
            self._json_ld_parts.append(data)
            return
        if self._excluded:
            return
        if self._in_document_title:
            self.document_title = (self.document_title or "") + data
        if self._in_body_tag:
            self.body_parts.append(data)


def extract_page(html: str) -> PageMetadata:
    parser = _PageParser()
    parser.feed(html)
    parser.close()

    published_at: datetime | None = None
    offset_minutes: int | None = None
    for candidate in parser.date_candidates:
        parsed = parse_timestamp(candidate)
        if parsed is not None:
            published_at, offset_minutes = parsed
            break

    title = parser.og_title or parser.document_title
    return PageMetadata(
        title=" ".join(title.split()) if title else None,
        site_name=" ".join(parser.site_name.split()) if parser.site_name else None,
        published_at=published_at,
        published_at_offset_minutes=offset_minutes,
        body=" ".join("".join(parser.body_parts).split()),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_gdelt_extract.py -v`

Expected: PASS, 16 tests.

- [ ] **Step 6: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/gdelt/extract.py packages/backend/tests/test_gdelt_extract.py packages/backend/tests/fixtures/article_*.html
git commit -m "feat: extract publication time and body from publisher pages"
```

---

### Task 10: Call the GDELT DOC 2.0 API

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/gdelt/api.py`
- Create: `packages/backend/tests/fixtures/gdelt_artlist.json`
- Test: `packages/backend/tests/test_gdelt_api.py`

- [ ] **Step 1: Create the fixture**

This is a verbatim copy of a live response captured on 2026-08-27. It contains
four syndicated copies of one measles story, which is retained deliberately as
evidence for sub-project B.

Create `packages/backend/tests/fixtures/gdelt_artlist.json`:

```json
{
  "articles": [
    {
      "url": "https://www.telemundodallas.com/noticias/eeuu/pensilvania-muerte-dos-pacientes-sarampion-no-vacunados/2599658/",
      "url_mobile": "https://www.telemundodallas.com/noticias/eeuu/pensilvania-muerte-dos-pacientes-sarampion-no-vacunados/2599658/?amp=1",
      "title": "Dos residentes no vacunados mueren de sarampion en Pensilvania - Telemundo Dallas ( 39 ) ",
      "seendate": "20260825T190000Z",
      "socialimage": "https://media.telemundodallas.com/2025/04/GettyImages-1358974423.jpg",
      "domain": "telemundodallas.com",
      "language": "Spanish",
      "sourcecountry": "United States"
    },
    {
      "url": "https://www.telemundo47.com/noticias/eeuu/pensilvania-muerte-dos-pacientes-sarampion-no-vacunados/2650887/",
      "url_mobile": "",
      "title": "Dos residentes no vacunados mueren de sarampion en Pensilvania - Telemundo New York ( 47 ) ",
      "seendate": "20260825T190000Z",
      "socialimage": "",
      "domain": "telemundo47.com",
      "language": "Spanish",
      "sourcecountry": "United States"
    },
    {
      "url": "https://www.thenational.scot/news/26487146.near-fatal-illness-inspired-highlanders-musical-voyage/",
      "url_mobile": "",
      "title": "How a near - fatal illness inspired a Highlander musical voyage",
      "seendate": "20260823T073000Z",
      "socialimage": "",
      "domain": "thenational.scot",
      "language": "English",
      "sourcecountry": "United Kingdom"
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

Create `packages/backend/tests/test_gdelt_api.py`:

```python
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from episignal_backend.ingestion.documents import QueryRule, TimeWindow
from episignal_backend.ingestion.gdelt.api import API_URL, GdeltDocClient, GdeltUnavailable

FIXTURES = Path(__file__).parent / "fixtures"
WINDOW = TimeWindow(
    start=datetime(2026, 8, 26, 7, 30, tzinfo=UTC),
    end=datetime(2026, 8, 26, 7, 50, tzinfo=UTC),
)
RULE = QueryRule(rule_group="known_disease", query="measles", label="Measles")


def client_returning(*responses: httpx.Response) -> GdeltDocClient:
    remaining = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        response = remaining.pop(0)
        response.request = request
        return response

    transport = httpx.MockTransport(handler)
    return GdeltDocClient(client=httpx.Client(transport=transport), sleep=lambda _: None)


def artlist_response() -> httpx.Response:
    return httpx.Response(200, json=json.loads((FIXTURES / "gdelt_artlist.json").read_text()))


def test_search_returns_one_article_per_entry() -> None:
    articles = client_returning(artlist_response()).search(RULE, WINDOW)
    assert len(articles) == 3


def test_search_maps_locale_names_to_codes() -> None:
    articles = client_returning(artlist_response()).search(RULE, WINDOW)
    assert articles[0].language == "es"
    assert articles[0].country_code == "US"


def test_search_parses_the_quantized_seendate() -> None:
    articles = client_returning(artlist_response()).search(RULE, WINDOW)
    assert articles[0].gdelt_seen_at == datetime(2026, 8, 25, 19, 0, tzinfo=UTC)


def test_search_canonicalizes_urls() -> None:
    articles = client_returning(artlist_response()).search(RULE, WINDOW)
    assert articles[0].canonical_url.endswith("2599658")


def test_search_carries_the_rule_identity() -> None:
    articles = client_returning(artlist_response()).search(RULE, WINDOW)
    assert all(article.query_rule_id == RULE.id for article in articles)


def test_search_sends_the_window_as_start_and_end_datetimes() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"articles": []}, request=request)

    client = GdeltDocClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None
    )
    client.search(RULE, WINDOW)

    assert str(captured[0].url).startswith(API_URL)
    assert captured[0].url.params["startdatetime"] == "20260826073000"
    assert captured[0].url.params["enddatetime"] == "20260826075000"
    assert captured[0].url.params["mode"] == "ArtList"
    assert captured[0].url.params["format"] == "json"


def test_an_empty_result_is_not_an_error() -> None:
    client = client_returning(httpx.Response(200, json={"articles": []}))
    assert client.search(RULE, WINDOW) == ()


def test_a_body_that_is_not_json_is_treated_as_empty() -> None:
    # GDELT answers an unmatched query with a bare message rather than JSON.
    client = client_returning(httpx.Response(200, text="No results found."))
    assert client.search(RULE, WINDOW) == ()


def test_search_retries_a_retryable_status_then_succeeds() -> None:
    client = client_returning(httpx.Response(429), artlist_response())
    assert len(client.search(RULE, WINDOW)) == 3


def test_search_raises_when_every_attempt_is_refused() -> None:
    client = client_returning(httpx.Response(503), httpx.Response(503), httpx.Response(503))
    with pytest.raises(GdeltUnavailable):
        client.search(RULE, WINDOW)


def test_search_raises_when_the_transport_refuses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = GdeltDocClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _: None
    )
    with pytest.raises(GdeltUnavailable):
        client.search(RULE, WINDOW)


def test_search_skips_an_entry_with_no_url() -> None:
    client = client_returning(
        httpx.Response(
            200,
            json={
                "articles": [
                    {"url": "", "title": "x", "seendate": "20260825T190000Z", "domain": "a.test"},
                    {
                        "url": "https://a.test/1",
                        "title": "Measles cases rise",
                        "seendate": "20260825T190000Z",
                        "domain": "a.test",
                        "language": "English",
                        "sourcecountry": "United Kingdom",
                    },
                ]
            },
        )
    )
    articles = client.search(RULE, WINDOW)
    assert len(articles) == 1
    assert articles[0].url == "https://a.test/1"


def test_search_waits_between_requests_when_asked() -> None:
    slept: list[float] = []
    client = client_returning(httpx.Response(429), artlist_response())
    client._sleep = slept.append  # type: ignore[method-assign]
    client.search(RULE, WINDOW)
    assert slept == [1.0]


def test_window_longer_than_a_day_is_accepted() -> None:
    window = TimeWindow(
        start=datetime(2026, 8, 20, tzinfo=UTC), end=datetime(2026, 8, 26, tzinfo=UTC)
    )
    assert len(client_returning(artlist_response()).search(RULE, window)) == 3
    assert window.end - window.start == timedelta(days=6)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_gdelt_api.py -v`

Expected: FAIL with `ModuleNotFoundError` for `api`.

- [ ] **Step 4: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ingestion/gdelt/api.py`:

```python
"""GDELT DOC 2.0 client.

Verified against the live API on 2026-08-27: an `ArtList` response is a JSON
object with one `articles` key, and each entry carries `url`, `url_mobile`,
`title`, `seendate`, `socialimage`, `domain`, `language`, and `sourcecountry`.
There is no publication date and no body text, which is why `article.py` exists.

`seendate` is quantized to fifteen minutes and records when the GDELT crawler
saw the article. It is stored as `gdelt_seen_at` and never as `published_at`.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from time import sleep as default_sleep
from typing import Any

import httpx

from episignal_backend.ingestion.documents import DiscoveredArticle, QueryRule, TimeWindow
from episignal_backend.ingestion.gdelt.locale import country_code, language_code
from episignal_backend.ingestion.urls import canonicalize_url

API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MAX_RECORDS = 250
TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 3
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
SEEN_FORMAT = "%Y%m%dT%H%M%SZ"
WINDOW_FORMAT = "%Y%m%d%H%M%S"


class GdeltUnavailable(Exception):
    """GDELT could not be reached or kept refusing.

    Expected rather than exceptional: the API rate-limits aggressively, and one
    unreachable rule must not fail a run covering fifty others.
    """


def parse_seen_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), SEEN_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


class GdeltDocClient:
    discovery_name = "GDELT"

    def __init__(
        self,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._sleep = sleep

    def search(self, rule: QueryRule, window: TimeWindow) -> tuple[DiscoveredArticle, ...]:
        parameters = {
            "query": rule.query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": str(MAX_RECORDS),
            "sort": "datedesc",
            "startdatetime": window.start.astimezone(UTC).strftime(WINDOW_FORMAT),
            "enddatetime": window.end.astimezone(UTC).strftime(WINDOW_FORMAT),
        }
        payload = self._request(parameters)
        entries = payload.get("articles")
        if not isinstance(entries, list):
            return ()

        articles: list[DiscoveredArticle] = []
        for entry in entries:
            article = self._article(entry, rule)
            if article is not None:
                articles.append(article)
        return tuple(articles)

    def _article(self, entry: object, rule: QueryRule) -> DiscoveredArticle | None:
        if not isinstance(entry, dict):
            return None
        url = str(entry.get("url") or "").strip()
        title = str(entry.get("title") or "").strip()
        domain = str(entry.get("domain") or "").strip()
        seen = parse_seen_date(str(entry.get("seendate") or ""))
        if not url or not title or not domain or seen is None:
            # A partial entry names no document we could ever fetch, so there is
            # nothing to keep and nothing to review.
            return None
        return DiscoveredArticle(
            url=url,
            canonical_url=canonicalize_url(url),
            title=title,
            domain=domain,
            gdelt_seen_at=seen,
            language=language_code(str(entry.get("language") or "")),
            country_code=country_code(str(entry.get("sourcecountry") or "")),
            query_rule_id=rule.id,
        )

    def _request(self, parameters: dict[str, str]) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._client.get(API_URL, params=parameters, timeout=TIMEOUT_SECONDS)
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
            else:
                if response.status_code not in RETRY_STATUS:
                    response.raise_for_status()
                    try:
                        payload = response.json()
                    except ValueError:
                        # GDELT answers an unmatched query with a bare sentence
                        # rather than JSON, which means no results, not a fault.
                        return {}
                    return payload if isinstance(payload, dict) else {}
                last_error = httpx.HTTPStatusError(
                    f"GDELT returned {response.status_code}",
                    request=response.request,
                    response=response,
                )

            if attempt < MAX_ATTEMPTS - 1:
                self._sleep(2.0**attempt)

        raise GdeltUnavailable("GDELT search failed") from last_error
```

Drop `Sequence` from the `collections.abc` import line — this module returns
tuples, not `Sequence`. `uv run ruff check .` will flag it if you leave it.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_gdelt_api.py -v`

Expected: PASS, 14 tests.

- [ ] **Step 6: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/gdelt/api.py packages/backend/tests/test_gdelt_api.py packages/backend/tests/fixtures/gdelt_artlist.json
git commit -m "feat: search the GDELT DOC 2.0 API"
```

---

### Task 11: Fetch publisher pages politely

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/gdelt/article.py`
- Test: `packages/backend/tests/test_gdelt_article.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_gdelt_article.py`:

```python
import httpx
import pytest

from episignal_backend.ingestion.gdelt.article import ArticleFetcher, Disallowed, Unfetchable

ROBOTS_ALLOW = "User-agent: *\nAllow: /\n"
ROBOTS_DENY_ALL = "User-agent: *\nDisallow: /\n"
ROBOTS_DENY_SECTION = "User-agent: *\nDisallow: /private/\n"
PAGE = "<html><body><p>Eighteen students were admitted.</p></body></html>"


def fetcher(routes: dict[str, httpx.Response], delays: list[float] | None = None) -> ArticleFetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        key = str(request.url)
        if key not in routes:
            return httpx.Response(404, request=request)
        response = routes[key]
        response.request = request
        return response

    return ArticleFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=(delays.append if delays is not None else lambda _: None),
        delay_seconds=1.0,
    )


def test_fetches_a_page_when_robots_allows_it() -> None:
    routes = {
        "https://example.vn/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW),
        "https://example.vn/a": httpx.Response(200, text=PAGE),
    }
    assert "Eighteen students" in fetcher(routes).fetch("https://example.vn/a")


def test_refuses_a_path_robots_disallows() -> None:
    routes = {
        "https://example.vn/robots.txt": httpx.Response(200, text=ROBOTS_DENY_ALL),
        "https://example.vn/a": httpx.Response(200, text=PAGE),
    }
    with pytest.raises(Disallowed):
        fetcher(routes).fetch("https://example.vn/a")


def test_allows_a_path_outside_a_disallowed_section() -> None:
    routes = {
        "https://example.vn/robots.txt": httpx.Response(200, text=ROBOTS_DENY_SECTION),
        "https://example.vn/public/a": httpx.Response(200, text=PAGE),
    }
    assert "Eighteen students" in fetcher(routes).fetch("https://example.vn/public/a")


def test_a_missing_robots_file_permits_fetching() -> None:
    routes = {
        "https://example.vn/robots.txt": httpx.Response(404),
        "https://example.vn/a": httpx.Response(200, text=PAGE),
    }
    assert "Eighteen students" in fetcher(routes).fetch("https://example.vn/a")


def test_robots_is_fetched_once_per_domain() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_ALLOW, request=request)
        return httpx.Response(200, text=PAGE, request=request)

    fetch = ArticleFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
        delay_seconds=0.0,
    )
    fetch.fetch("https://example.vn/a")
    fetch.fetch("https://example.vn/b")

    assert requested.count("https://example.vn/robots.txt") == 1


def test_waits_between_two_fetches_of_the_same_domain() -> None:
    delays: list[float] = []
    routes = {
        "https://example.vn/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW),
        "https://example.vn/a": httpx.Response(200, text=PAGE),
        "https://example.vn/b": httpx.Response(200, text=PAGE),
    }
    fetch = fetcher(routes, delays)
    fetch.fetch("https://example.vn/a")
    fetch.fetch("https://example.vn/b")
    assert delays == [1.0]


def test_an_error_status_is_unfetchable() -> None:
    routes = {
        "https://example.vn/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW),
        "https://example.vn/a": httpx.Response(403),
    }
    with pytest.raises(Unfetchable):
        fetcher(routes).fetch("https://example.vn/a")


def test_a_transport_refusal_is_unfetchable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS_ALLOW, request=request)
        raise httpx.ConnectTimeout("timed out", request=request)

    fetch = ArticleFetcher(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
        delay_seconds=0.0,
    )
    with pytest.raises(Unfetchable):
        fetch.fetch("https://example.vn/a")


def test_a_non_html_response_is_unfetchable() -> None:
    routes = {
        "https://example.vn/robots.txt": httpx.Response(200, text=ROBOTS_ALLOW),
        "https://example.vn/a.pdf": httpx.Response(
            200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}
        ),
    }
    with pytest.raises(Unfetchable):
        fetcher(routes).fetch("https://example.vn/a.pdf")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_gdelt_article.py -v`

Expected: FAIL with `ModuleNotFoundError` for `article`.

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ingestion/gdelt/article.py`:

```python
"""Fetching the publisher's page.

This is the only place EpiSignal reads a third party's website rather than an
API offered to it, so it behaves like a guest: one robots.txt check per domain,
a delay between consecutive requests to the same host, and a User-Agent that
says who is calling and where to complain.

A refusal is expected, not exceptional. `Unfetchable` and `Disallowed` are
distinct because one warrants a retry and the other never will.
"""

import logging
from collections.abc import Callable
from time import monotonic
from time import sleep as default_sleep
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "EpiSignal/0.1 (+https://episignal.org)"
TIMEOUT_SECONDS = 15.0
DELAY_SECONDS = 1.0
MAX_BYTES = 2_000_000
HTML_TYPES = ("text/html", "application/xhtml+xml", "text/plain")

logger = logging.getLogger("episignal_backend.ingestion.gdelt")


class Unfetchable(Exception):
    """The page could not be retrieved. Worth retrying later."""


class Disallowed(Exception):
    """robots.txt forbids this path. Never worth retrying."""


class ArticleFetcher:
    def __init__(
        self,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = default_sleep,
        delay_seconds: float = DELAY_SECONDS,
        user_agent: str = USER_AGENT,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=timeout_seconds, follow_redirects=True, headers={"User-Agent": user_agent}
        )
        self._sleep = sleep
        self._delay_seconds = delay_seconds
        self._user_agent = user_agent
        self._timeout_seconds = timeout_seconds
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last_request: dict[str, float] = {}

    def fetch(self, url: str) -> str:
        parsed = urlsplit(url)
        host = parsed.netloc.lower()

        if not self._permitted(parsed.scheme, host, url):
            raise Disallowed(host)

        self._wait_for(host)
        try:
            response = self._client.get(
                url, timeout=self._timeout_seconds, headers={"User-Agent": self._user_agent}
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            raise Unfetchable(host) from error
        finally:
            self._last_request[host] = monotonic()

        if response.status_code >= 400:
            raise Unfetchable(f"{host} returned {response.status_code}")

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith(HTML_TYPES):
            raise Unfetchable(f"{host} returned {content_type}")

        if len(response.content) > MAX_BYTES:
            raise Unfetchable(f"{host} returned an oversized document")

        return response.text

    def _permitted(self, scheme: str, host: str, url: str) -> bool:
        if host not in self._robots:
            self._robots[host] = self._read_robots(scheme or "https", host)
        rules = self._robots[host]
        # An absent or unreadable robots.txt is permission by convention; a
        # present one that forbids the path is not ours to overrule.
        return True if rules is None else rules.can_fetch(self._user_agent, url)

    def _read_robots(self, scheme: str, host: str) -> RobotFileParser | None:
        location = f"{scheme}://{host}/robots.txt"
        try:
            response = self._client.get(
                location, timeout=self._timeout_seconds, headers={"User-Agent": self._user_agent}
            )
        except (httpx.TimeoutException, httpx.TransportError):
            return None
        if response.status_code >= 400:
            return None
        parser = RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser

    def _wait_for(self, host: str) -> None:
        previous = self._last_request.get(host)
        if previous is None or self._delay_seconds <= 0:
            return
        remaining = self._delay_seconds - (monotonic() - previous)
        if remaining > 0:
            self._sleep(self._delay_seconds)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_gdelt_article.py -v`

Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/gdelt/article.py packages/backend/tests/test_gdelt_article.py
git commit -m "feat: fetch publisher pages politely"
```

---

### Task 12: Assemble the connector

`retrieve` is where GDELT metadata and the publisher's page become one signal.
It is the only place that decides a discovery is a stub rather than evidence.

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/gdelt/connector.py`
- Test: `packages/backend/tests/test_gdelt_connector.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_gdelt_connector.py`:

```python
from datetime import UTC, datetime, timedelta, timezone

import pytest

from episignal_backend.db.types import ProcessingStatus
from episignal_backend.ingestion.documents import DiscoveredArticle, QueryRule, TimeWindow
from episignal_backend.ingestion.gdelt.article import Disallowed, Unfetchable
from episignal_backend.ingestion.gdelt.connector import GdeltConnector
from episignal_backend.ingestion.protocol import DiscoveryConnector, RetrievalFailed

SEEN = datetime(2026, 8, 26, 7, 45, tzinfo=UTC)
FIRST = datetime(2026, 8, 26, 7, 51, tzinfo=UTC)
NOW = datetime(2026, 8, 26, 7, 52, tzinfo=UTC)

FULL_PAGE = """
<html><head>
<meta property="og:title" content="18 students hospitalised" />
<meta property="og:site_name" content="Example News Vietnam" />
<meta property="article:published_time" content="2026-08-26T07:42:00+07:00" />
</head><body><p>Eighteen students were admitted on Tuesday.</p></body></html>
"""

NO_DATE_PAGE = "<html><body><p>Eleven people fell ill after a shared meal.</p></body></html>"
NO_BODY_PAGE = "<html><head><title>Subscribe</title></head><body><div>Subscribe</div></body></html>"


class FakeSearch:
    def __init__(self, articles: tuple[DiscoveredArticle, ...] = ()) -> None:
        self.articles = articles

    def search(self, rule: QueryRule, window: TimeWindow) -> tuple[DiscoveredArticle, ...]:
        return self.articles


class FakeFetcher:
    def __init__(self, result: str | Exception) -> None:
        self.result = result
        self.calls: list[str] = []

    def fetch(self, url: str) -> str:
        self.calls.append(url)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def article() -> DiscoveredArticle:
    return DiscoveredArticle(
        url="https://example.vn/a",
        canonical_url="https://example.vn/a",
        title="Dos residentes - Example News ( 39 )",
        domain="example.vn",
        gdelt_seen_at=SEEN,
        language="vi",
        country_code="VN",
    )


def connector(page: str | Exception) -> GdeltConnector:
    return GdeltConnector(
        search=FakeSearch(),  # type: ignore[arg-type]
        fetcher=FakeFetcher(page),  # type: ignore[arg-type]
        now=lambda: NOW,
        # The production floor is 200 characters, which every fixture here would
        # trip. The behaviour under test is the decision, not the threshold.
        minimum_body_characters=20,
    )


def test_connector_satisfies_the_protocol() -> None:
    assert isinstance(connector(FULL_PAGE), DiscoveryConnector)


def test_retrieve_prefers_the_publisher_title() -> None:
    signal = connector(FULL_PAGE).retrieve(article(), FIRST)
    assert signal.title == "18 students hospitalised"


def test_retrieve_falls_back_to_the_gdelt_title() -> None:
    signal = connector(NO_DATE_PAGE).retrieve(article(), FIRST)
    assert signal.title == "Dos residentes - Example News ( 39 )"


def test_retrieve_keeps_the_stated_publication_offset() -> None:
    signal = connector(FULL_PAGE).retrieve(article(), FIRST)
    assert signal.published_at == datetime(
        2026, 8, 26, 7, 42, tzinfo=timezone(timedelta(hours=7))
    )
    assert signal.published_at_offset_minutes == 420


def test_retrieve_never_substitutes_the_seen_date_for_a_publication_date() -> None:
    signal = connector(NO_DATE_PAGE).retrieve(article(), FIRST)
    assert signal.published_at is None
    assert signal.published_at_offset_minutes is None
    assert signal.gdelt_seen_at == SEEN


def test_retrieve_keeps_the_first_seen_time_it_was_given() -> None:
    signal = connector(FULL_PAGE).retrieve(article(), FIRST)
    assert signal.first_seen_at == FIRST
    assert signal.retrieved_at == NOW


def test_retrieve_names_the_publisher_from_the_page() -> None:
    signal = connector(FULL_PAGE).retrieve(article(), FIRST)
    assert signal.publisher.domain == "example.vn"
    assert signal.publisher.name == "Example News Vietnam"
    assert signal.publisher.country_code == "VN"


def test_retrieve_names_the_publisher_from_the_domain_when_the_page_is_silent() -> None:
    signal = connector(NO_DATE_PAGE).retrieve(article(), FIRST)
    assert signal.publisher.name == "example.vn"


def test_a_page_without_prose_is_a_retrieval_failure() -> None:
    with pytest.raises(RetrievalFailed):
        connector(NO_BODY_PAGE).retrieve(article(), FIRST)


def test_an_unfetchable_page_is_a_retrieval_failure() -> None:
    with pytest.raises(RetrievalFailed):
        connector(Unfetchable("blocked")).retrieve(article(), FIRST)


def test_a_disallowed_page_is_a_retrieval_failure() -> None:
    with pytest.raises(RetrievalFailed):
        connector(Disallowed("example.vn")).retrieve(article(), FIRST)


def test_the_content_hash_changes_when_the_body_changes() -> None:
    first = connector(FULL_PAGE).retrieve(article(), FIRST)
    changed = FULL_PAGE.replace("Eighteen students", "Twenty students")
    second = connector(changed).retrieve(article(), FIRST)
    assert first.content_hash != second.content_hash


def test_stub_for_a_failed_retrieval_is_built_by_the_connector() -> None:
    stub = connector(FULL_PAGE).stub(article(), FIRST)
    assert stub.processing_status is ProcessingStatus.NEEDS_REVIEW
    assert stub.raw_text is None
    assert stub.published_at is None
    assert stub.title == "Dos residentes - Example News ( 39 )"
    assert stub.publisher.name == "example.vn"
    assert len(stub.content_hash) == 64
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_gdelt_connector.py -v`

Expected: FAIL with `ModuleNotFoundError` for `connector`.

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ingestion/gdelt/connector.py`:

```python
"""Where a GDELT sighting and a publisher's page become one signal.

GDELT supplies the URL, the domain, and the moment its crawler saw the article.
The publisher's page supplies the headline, the publication time, and the text.
Neither is allowed to stand in for the other: a missing publication time stays
missing rather than borrowing the crawler's clock.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from episignal_backend.db.types import ProcessingStatus
from episignal_backend.ingestion.documents import (
    DiscoveredArticle,
    DiscoveredSignal,
    Publisher,
    QueryRule,
    TimeWindow,
)
from episignal_backend.ingestion.fingerprint import content_hash
from episignal_backend.ingestion.gdelt.api import GdeltDocClient
from episignal_backend.ingestion.gdelt.article import ArticleFetcher, Disallowed, Unfetchable
from episignal_backend.ingestion.gdelt.extract import extract_page
from episignal_backend.ingestion.protocol import RetrievalFailed

DISCOVERY_NAME = "GDELT"
MINIMUM_BODY_CHARACTERS = 200


def _utc_now() -> datetime:
    return datetime.now(UTC)


class GdeltConnector:
    discovery_name = DISCOVERY_NAME

    def __init__(
        self,
        search: GdeltDocClient | None = None,
        fetcher: ArticleFetcher | None = None,
        now: Callable[[], datetime] = _utc_now,
        minimum_body_characters: int = MINIMUM_BODY_CHARACTERS,
    ) -> None:
        self._search = search or GdeltDocClient()
        self._fetcher = fetcher or ArticleFetcher()
        self._now = now
        self._minimum_body_characters = minimum_body_characters

    def discover(self, rule: QueryRule, window: TimeWindow) -> Sequence[DiscoveredArticle]:
        return self._search.search(rule, window)

    def retrieve(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        try:
            html = self._fetcher.fetch(article.url)
        except (Unfetchable, Disallowed) as reason:
            raise RetrievalFailed(str(reason)) from reason

        page = extract_page(html)
        # A page whose prose is shorter than a paragraph is a paywall notice or
        # a consent wall, not an article. Storing it would give sub-project C
        # nothing to read and would overstate what we hold.
        if len(page.body) < self._minimum_body_characters:
            raise RetrievalFailed(f"{article.domain} returned no article body")

        title = page.title or article.title
        return DiscoveredSignal(
            url=article.url,
            canonical_url=article.canonical_url,
            title=title,
            raw_text=page.body,
            published_at=page.published_at,
            published_at_offset_minutes=page.published_at_offset_minutes,
            retrieved_at=self._now(),
            first_seen_at=first_seen_at,
            gdelt_seen_at=article.gdelt_seen_at,
            language=article.language,
            content_hash=content_hash(title, page.body),
            publisher=self._publisher(article, page.site_name),
            query_rule_id=article.query_rule_id,
            processing_status=ProcessingStatus.FETCHED,
        )

    def stub(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        """A discovery whose page could not be read.

        Kept rather than dropped: the sighting is itself evidence, a user can
        still open the original URL, and the row stays countable as a failure.
        The hash covers the title alone, because there is no body to cover.
        """
        return DiscoveredSignal(
            url=article.url,
            canonical_url=article.canonical_url,
            title=article.title,
            raw_text=None,
            published_at=None,
            published_at_offset_minutes=None,
            retrieved_at=self._now(),
            first_seen_at=first_seen_at,
            gdelt_seen_at=article.gdelt_seen_at,
            language=article.language,
            content_hash=content_hash(article.title, ""),
            publisher=self._publisher(article, None),
            query_rule_id=article.query_rule_id,
            processing_status=ProcessingStatus.NEEDS_REVIEW,
        )

    def _publisher(self, article: DiscoveredArticle, site_name: str | None) -> Publisher:
        return Publisher(
            domain=article.domain,
            name=site_name or article.domain,
            language=article.language,
            country_code=article.country_code,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_gdelt_connector.py -v`

Expected: PASS, 13 tests.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/gdelt/connector.py packages/backend/tests/test_gdelt_connector.py
git commit -m "feat: assemble GDELT sightings and publisher pages into signals"
```

---

### Task 13: Run the discovery pipeline

This is the decision module. It imports neither SQLAlchemy nor httpx, so every
branch is exercised with in-memory fakes.

The ordering constraint that matters: the seen-URL check runs before any
retrieval. A run that fetched first would pay for thousands of pages it already
holds.

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/discovery.py`
- Test: `packages/backend/tests/test_discovery_pipeline.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_discovery_pipeline.py`:

```python
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from episignal_backend.db.types import ProcessingStatus
from episignal_backend.ingestion.discovery import DiscoveryResult, run_discovery
from episignal_backend.ingestion.documents import (
    DiscoveredArticle,
    DiscoveredSignal,
    Publisher,
    QueryRule,
    TimeWindow,
)
from episignal_backend.ingestion.gdelt.api import GdeltUnavailable
from episignal_backend.ingestion.protocol import RetrievalFailed

NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
SEEN = datetime(2026, 8, 26, 7, 45, tzinfo=UTC)
RULE = QueryRule(id=uuid4(), rule_group="syndromic", query='"unknown fever"', label="Unknown fever")


def article(path: str, domain: str = "example.vn") -> DiscoveredArticle:
    return DiscoveredArticle(
        url=f"https://{domain}{path}",
        canonical_url=f"https://{domain}{path}",
        title=f"Report {path}",
        domain=domain,
        gdelt_seen_at=SEEN,
        language="vi",
        country_code="VN",
        query_rule_id=RULE.id,
    )


class FakeRepository:
    def __init__(self, seen: set[str] | None = None) -> None:
        self.seen = seen or set()
        self.added: list[tuple[DiscoveredSignal, UUID]] = []
        self.publishers: dict[str, UUID] = {}
        self.commits = 0
        self.rollbacks = 0
        self.first_seen: dict[str, datetime] = {}

    def active_rules(self) -> Sequence[QueryRule]:
        return (RULE,)

    def seen_urls(self, canonical_urls: Sequence[str]) -> frozenset[str]:
        return frozenset(url for url in canonical_urls if url in self.seen)

    def first_seen_at(self, canonical_url: str) -> datetime | None:
        return self.first_seen.get(canonical_url)

    def publisher_source_id(self, publisher: Publisher) -> UUID:
        if publisher.domain not in self.publishers:
            self.publishers[publisher.domain] = uuid4()
        return self.publishers[publisher.domain]

    def add(self, signal: DiscoveredSignal, source_id: UUID) -> None:
        self.added.append((signal, source_id))

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeConnector:
    discovery_name = "GDELT"

    def __init__(
        self,
        articles: tuple[DiscoveredArticle, ...] = (),
        failing: frozenset[str] = frozenset(),
        unavailable: bool = False,
    ) -> None:
        self.articles = articles
        self.failing = failing
        self.unavailable = unavailable
        self.retrieved: list[str] = []

    def discover(self, rule: QueryRule, window: TimeWindow) -> Sequence[DiscoveredArticle]:
        if self.unavailable:
            raise GdeltUnavailable("refused")
        return self.articles

    def retrieve(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        self.retrieved.append(article.canonical_url)
        if article.canonical_url in self.failing:
            raise RetrievalFailed("blocked")
        return self._signal(article, first_seen_at, ProcessingStatus.FETCHED, "Body text here.")

    def stub(self, article: DiscoveredArticle, first_seen_at: datetime) -> DiscoveredSignal:
        return self._signal(article, first_seen_at, ProcessingStatus.NEEDS_REVIEW, None)

    def _signal(
        self,
        article: DiscoveredArticle,
        first_seen_at: datetime,
        status: ProcessingStatus,
        body: str | None,
    ) -> DiscoveredSignal:
        return DiscoveredSignal(
            url=article.url,
            canonical_url=article.canonical_url,
            title=article.title,
            raw_text=body,
            retrieved_at=NOW,
            first_seen_at=first_seen_at,
            gdelt_seen_at=article.gdelt_seen_at,
            language=article.language,
            content_hash=f"{abs(hash(article.canonical_url + str(status))):064x}"[:64],
            publisher=Publisher(
                domain=article.domain, name=article.domain, language="vi", country_code="VN"
            ),
            query_rule_id=article.query_rule_id,
            processing_status=status,
        )


def run(connector: FakeConnector, repository: FakeRepository, **kwargs: object) -> DiscoveryResult:
    return run_discovery(repository, connector, now=NOW, **kwargs)  # type: ignore[arg-type]


def test_stores_a_discovered_article() -> None:
    repository = FakeRepository()
    result = run(FakeConnector((article("/a"),)), repository)
    assert result.stored == 1
    assert repository.added[0][0].canonical_url == "https://example.vn/a"


def test_already_seen_urls_are_never_retrieved() -> None:
    repository = FakeRepository(seen={"https://example.vn/a"})
    connector = FakeConnector((article("/a"), article("/b")))
    result = run(connector, repository)

    # The ordering that matters: a URL already stored costs no page fetch.
    assert connector.retrieved == ["https://example.vn/b"]
    assert result.duplicate == 1
    assert result.stored == 1


def test_the_per_run_cap_bounds_retrieval() -> None:
    repository = FakeRepository()
    connector = FakeConnector(tuple(article(f"/{index}") for index in range(10)))
    result = run(connector, repository, max_articles=3)
    assert len(connector.retrieved) == 3
    assert result.stored == 3
    assert result.deferred == 7


def test_the_cap_takes_the_oldest_sightings_first() -> None:
    repository = FakeRepository()
    older = DiscoveredArticle(
        url="https://example.vn/old",
        canonical_url="https://example.vn/old",
        title="Older",
        domain="example.vn",
        gdelt_seen_at=SEEN - timedelta(hours=2),
    )
    connector = FakeConnector((article("/new"), older))
    run(connector, repository, max_articles=1)
    assert connector.retrieved == ["https://example.vn/old"]


def test_a_failed_retrieval_stores_a_stub_and_continues() -> None:
    repository = FakeRepository()
    connector = FakeConnector(
        (article("/a"), article("/b")), failing=frozenset({"https://example.vn/a"})
    )
    result = run(connector, repository)

    assert result.stored == 1
    assert result.needs_review == 1
    statuses = {signal.canonical_url: signal.processing_status for signal, _ in repository.added}
    assert statuses["https://example.vn/a"] is ProcessingStatus.NEEDS_REVIEW
    assert statuses["https://example.vn/b"] is ProcessingStatus.FETCHED


def test_publisher_registration_is_reused_within_a_run() -> None:
    repository = FakeRepository()
    run(FakeConnector((article("/a"), article("/b"))), repository)
    assert len(repository.publishers) == 1
    assert repository.added[0][1] == repository.added[1][1]


def test_two_publishers_get_two_sources() -> None:
    repository = FakeRepository()
    run(FakeConnector((article("/a"), article("/b", domain="other.vn"))), repository)
    assert len(repository.publishers) == 2


def test_a_known_url_keeps_its_original_first_seen_time() -> None:
    earlier = NOW - timedelta(days=3)
    repository = FakeRepository()
    repository.first_seen["https://example.vn/a"] = earlier
    run(FakeConnector((article("/a"),)), repository)
    assert repository.added[0][0].first_seen_at == earlier


def test_a_new_url_is_first_seen_now() -> None:
    repository = FakeRepository()
    run(FakeConnector((article("/a"),)), repository)
    assert repository.added[0][0].first_seen_at == NOW


def test_an_unavailable_rule_is_counted_not_raised() -> None:
    repository = FakeRepository()
    result = run(FakeConnector(unavailable=True), repository)
    assert result.rules_failed == 1
    assert result.stored == 0


def test_a_run_with_no_rules_reports_no_rules() -> None:
    class NoRules(FakeRepository):
        def active_rules(self) -> Sequence[QueryRule]:
            return ()

    result = run(FakeConnector(), NoRules())
    assert result.rules_run == 0


def test_the_window_ends_at_the_run_time() -> None:
    captured: list[TimeWindow] = []

    class Recording(FakeConnector):
        def discover(self, rule: QueryRule, window: TimeWindow) -> Sequence[DiscoveredArticle]:
            captured.append(window)
            return ()

    run(Recording(), FakeRepository(), window_minutes=20)
    assert captured[0].end == NOW
    assert captured[0].start == NOW - timedelta(minutes=20)


def test_a_storage_failure_rolls_back_and_continues() -> None:
    class Failing(FakeRepository):
        def add(self, signal: DiscoveredSignal, source_id: UUID) -> None:
            if signal.canonical_url.endswith("/a"):
                raise RuntimeError("constraint violated")
            super().add(signal, source_id)

    repository = Failing()
    result = run(FakeConnector((article("/a"), article("/b"))), repository)
    assert result.failed == 1
    assert result.stored == 1
    assert repository.rollbacks == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_discovery_pipeline.py -v`

Expected: FAIL with `ModuleNotFoundError` for `discovery`.

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ingestion/discovery.py`:

```python
"""Discovery decisions.

This module imports neither SQLAlchemy nor httpx. It depends on the two
Protocols in `protocol.py`, which is what makes every decision below testable
with in-memory fakes and no credentials.

The ordering here is the whole point of the module: GDELT names far more
articles than are worth fetching, so already-stored URLs are dropped before any
publisher connection is opened, and what remains is capped.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from episignal_backend.ingestion.documents import DiscoveredArticle, TimeWindow
from episignal_backend.ingestion.protocol import (
    DiscoveryConnector,
    DiscoveryRepository,
    RetrievalFailed,
)

DEFAULT_WINDOW_MINUTES = 20
DEFAULT_MAX_ARTICLES = 200

logger = logging.getLogger("episignal_backend.ingestion.discovery")


@dataclass(frozen=True)
class DiscoveryResult:
    rules_run: int = 0
    rules_failed: int = 0
    discovered: int = 0
    duplicate: int = 0
    deferred: int = 0
    stored: int = 0
    needs_review: int = 0
    failed: int = 0


def run_discovery(
    repository: DiscoveryRepository,
    connector: DiscoveryConnector,
    *,
    now: datetime | None = None,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    max_articles: int = DEFAULT_MAX_ARTICLES,
) -> DiscoveryResult:
    moment = now or datetime.now(UTC)
    window = TimeWindow(start=moment - timedelta(minutes=window_minutes), end=moment)

    rules = repository.active_rules()
    rules_failed = 0
    discovered: dict[str, DiscoveredArticle] = {}

    for rule in rules:
        try:
            found = connector.discover(rule, window)
        except Exception as error:
            # One rate-limited rule must not discard the other forty-nine.
            rules_failed += 1
            logger.warning(
                "Discovery rule %s failed (%s)",
                rule.label,
                type(error).__name__,
            )
            continue
        for article in found:
            # Within a run the same story arrives under several rules; the first
            # sighting keeps the rule that found it.
            discovered.setdefault(article.canonical_url, article)

    already_stored = repository.seen_urls(tuple(discovered))
    candidates = [
        article
        for canonical_url, article in discovered.items()
        if canonical_url not in already_stored
    ]
    # Oldest first, so a burst of fresh articles never starves a discovery that
    # has already been waiting for a slot.
    candidates.sort(key=lambda article: article.gdelt_seen_at)
    selected = candidates[:max_articles]

    stored = 0
    needs_review = 0
    failed = 0

    for article in selected:
        first_seen = repository.first_seen_at(article.canonical_url) or moment
        try:
            signal = connector.retrieve(article, first_seen)
        except RetrievalFailed as reason:
            signal = connector.stub(article, first_seen)
            logger.info(
                "Stored %s as needs_review (%s)",
                article.canonical_url,
                reason,
            )

        try:
            source_id = repository.publisher_source_id(signal.publisher)
            repository.add(signal, source_id)
            repository.commit()
        except Exception as error:
            repository.rollback()
            failed += 1
            logger.error(
                "Could not store %s (%s)",
                article.canonical_url,
                type(error).__name__,
            )
            continue

        if signal.raw_text is None:
            needs_review += 1
        else:
            stored += 1

    return DiscoveryResult(
        rules_run=len(rules),
        rules_failed=rules_failed,
        discovered=len(discovered),
        duplicate=len(already_stored),
        deferred=len(candidates) - len(selected),
        stored=stored,
        needs_review=needs_review,
        failed=failed,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_discovery_pipeline.py -v`

Expected: PASS, 13 tests.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest`

Expected: PASS. Every WHO and ECDC test still passes.

- [ ] **Step 6: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/discovery.py packages/backend/src/episignal_backend/ingestion/protocol.py packages/backend/tests/test_discovery_pipeline.py
git commit -m "feat: run the GDELT discovery pipeline"
```

---

### Task 14: Store discovered signals

**Files:**
- Modify: `packages/backend/src/episignal_backend/ingestion/repository.py`
- Test: `packages/backend/tests/test_discovery_repository.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_discovery_repository.py`:

Note the pattern: no test in this repository opens a database. `build_*`
functions are tested as pure mappings, and the session is faked. SQLite is not a
substitute here — `IdentityMixin` defaults the primary key to
`gen_random_uuid()`, which SQLite does not have.

```python
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from episignal_backend.db.types import DiscoveryMethod, ProcessingStatus
from episignal_backend.ingestion.documents import DiscoveredSignal, Publisher
from episignal_backend.ingestion.repository import build_discovered_signal

NOW = datetime(2026, 8, 26, 8, 0, tzinfo=UTC)
SEEN = datetime(2026, 8, 26, 7, 45, tzinfo=UTC)
FIRST = datetime(2026, 8, 20, 6, 0, tzinfo=UTC)


def discovered(**overrides: object) -> DiscoveredSignal:
    values: dict[str, object] = {
        "url": "https://example.vn/a",
        "canonical_url": "https://example.vn/a",
        "title": "18 students hospitalised",
        "raw_text": "Eighteen students were admitted.",
        "published_at": NOW,
        "published_at_offset_minutes": 420,
        "retrieved_at": NOW,
        "first_seen_at": FIRST,
        "gdelt_seen_at": SEEN,
        "language": "vi",
        "content_hash": "c" * 64,
        "publisher": Publisher(
            domain="example.vn", name="Example News", language="vi", country_code="VN"
        ),
    }
    return DiscoveredSignal(**(values | overrides))  # type: ignore[arg-type]


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value


class FakeSession:
    """Answers `execute` from a queue and assigns ids on flush.

    The real session cannot be used: the primary key defaults to
    `gen_random_uuid()`, which only PostgreSQL provides.
    """

    def __init__(self, results: list[Any]) -> None:
        self.results = results
        self.added: list[Any] = []
        self.rollbacks = 0

    def execute(self, statement: Any) -> FakeResult:
        return FakeResult(self.results.pop(0))

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid4()

    def rollback(self) -> None:
        self.rollbacks += 1


def test_a_discovered_signal_is_marked_as_discovered_via_gdelt() -> None:
    row = build_discovered_signal(discovered(), uuid4())
    assert row.discovered_via is DiscoveryMethod.GDELT


def test_a_discovered_signal_keeps_all_four_timestamps_apart() -> None:
    row = build_discovered_signal(discovered(), uuid4())
    assert row.published_at == NOW
    assert row.first_seen_at == FIRST
    assert row.retrieved_at == NOW
    assert row.gdelt_seen_at == SEEN
    assert row.published_at_offset_minutes == 420


def test_a_stub_carries_no_body_and_no_publication_time() -> None:
    row = build_discovered_signal(
        discovered(
            raw_text=None,
            published_at=None,
            published_at_offset_minutes=None,
            processing_status=ProcessingStatus.NEEDS_REVIEW,
        ),
        uuid4(),
    )
    assert row.raw_text is None
    assert row.published_at is None
    assert row.processing_status is ProcessingStatus.NEEDS_REVIEW


def publisher() -> Publisher:
    return Publisher(domain="example.vn", name="Example News", language="vi", country_code="VN")


def test_a_known_domain_reuses_its_existing_source() -> None:
    from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository

    existing = uuid4()
    session = FakeSession([existing])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]

    assert repository.publisher_source_id(publisher()) == existing
    assert session.added == []


def test_an_unknown_domain_registers_a_local_media_source() -> None:
    from episignal_backend.db.types import CredibilityTier, SourceType
    from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository

    # No source for the domain, and no source holding the display name.
    session = FakeSession([None, None])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]
    source_id = repository.publisher_source_id(publisher())

    registered = session.added[0]
    assert registered.id == source_id
    assert registered.domain == "example.vn"
    assert registered.name == "Example News"
    assert registered.base_url == "https://example.vn"
    assert registered.source_type is SourceType.LOCAL_MEDIA
    assert registered.credibility_tier is CredibilityTier.UNKNOWN
    # A discovered publisher is never official: only an official body can
    # confirm, and GDELT finding an article grants no authority.
    assert registered.is_official is False


def test_a_colliding_publisher_name_falls_back_to_the_domain() -> None:
    from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository

    # No source for the domain, but the display name is already taken.
    session = FakeSession([None, uuid4()])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]
    repository.publisher_source_id(publisher())

    # A shared display name is cosmetic; a lost discovery is not.
    assert session.added[0].name == "example.vn"
    assert session.added[0].domain == "example.vn"


def test_seen_urls_asks_nothing_when_given_nothing() -> None:
    from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository

    session = FakeSession([])
    repository = SqlAlchemyDiscoveryRepository(session)  # type: ignore[arg-type]
    # An empty IN clause is both wasteful and, on some drivers, invalid.
    assert repository.seen_urls(()) == frozenset()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_discovery_repository.py -v`

Expected: FAIL with `ImportError: cannot import name 'build_discovered_signal'`.

- [ ] **Step 3: Write minimal implementation**

Append to `packages/backend/src/episignal_backend/ingestion/repository.py`. Extend
the imports at the top of the file:

```python
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from episignal_backend.db.types import CredibilityTier, DiscoveryMethod, SourceType
from episignal_backend.ingestion.documents import DiscoveredSignal, NormalizedSignal, Publisher, QueryRule
from episignal_backend.models import GdeltQueryRule, Signal, Source
```

Then append:

```python
def build_discovered_signal(signal: DiscoveredSignal, source_id: UUID) -> Signal:
    return Signal(
        source_id=source_id,
        url=signal.url,
        canonical_url=signal.canonical_url,
        title=signal.title,
        raw_text=signal.raw_text,
        published_at=signal.published_at,
        published_at_offset_minutes=signal.published_at_offset_minutes,
        retrieved_at=signal.retrieved_at,
        first_seen_at=signal.first_seen_at,
        gdelt_seen_at=signal.gdelt_seen_at,
        language=signal.language,
        content_hash=signal.content_hash,
        discovered_via=DiscoveryMethod.GDELT,
        query_rule_id=signal.query_rule_id,
        processing_status=signal.processing_status,
    )


class SqlAlchemyDiscoveryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def active_rules(self) -> Sequence[QueryRule]:
        rows = self._session.execute(
            select(GdeltQueryRule).where(GdeltQueryRule.active.is_(True)).order_by(
                GdeltQueryRule.rule_group, GdeltQueryRule.label
            )
        ).scalars()
        return tuple(
            QueryRule(
                id=row.id,
                rule_group=row.rule_group,
                query=row.query,
                label=row.label,
                language=row.language,
            )
            for row in rows
        )

    def seen_urls(self, canonical_urls: Sequence[str]) -> frozenset[str]:
        if not canonical_urls:
            return frozenset()
        found = self._session.execute(
            select(Signal.canonical_url).where(Signal.canonical_url.in_(tuple(canonical_urls)))
        ).scalars()
        return frozenset(url for url in found if url is not None)

    def first_seen_at(self, canonical_url: str) -> datetime | None:
        return self._session.execute(
            select(func.min(Signal.first_seen_at)).where(Signal.canonical_url == canonical_url)
        ).scalar_one_or_none()

    def publisher_source_id(self, publisher: Publisher) -> UUID:
        existing = self._session.execute(
            select(Source.id).where(Source.domain == publisher.domain)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        taken = self._session.execute(
            select(Source.id).where(Source.name == publisher.name)
        ).scalar_one_or_none()
        # A display name shared with another outlet is cosmetic; refusing to
        # register the publisher would lose the discovery entirely.
        name = publisher.domain if taken is not None else publisher.name

        source = Source(
            name=name,
            source_type=SourceType.LOCAL_MEDIA,
            country_code=publisher.country_code,
            base_url=f"https://{publisher.domain}",
            domain=publisher.domain,
            credibility_tier=CredibilityTier.UNKNOWN,
            is_official=False,
            language=publisher.language or "en",
            active=True,
        )
        self._session.add(source)
        try:
            self._session.flush()
        except IntegrityError:
            # A concurrent run registered the same domain first. Its row is as
            # good as ours.
            self._session.rollback()
            return self._session.execute(
                select(Source.id).where(Source.domain == publisher.domain)
            ).scalar_one()
        return source.id

    def add(self, signal: DiscoveredSignal, source_id: UUID) -> None:
        self._session.add(build_discovered_signal(signal, source_id))
        self._session.flush()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_discovery_repository.py -v`

Expected: PASS, 7 tests.

- [ ] **Step 5: Confirm the repository satisfies the Protocol**

Add to `packages/backend/tests/test_discovery_repository.py`, matching the
pattern in `test_ingestion_repository.py`:

```python
def _conforms(repository: DiscoveryRepository) -> DiscoveryRepository:
    # mypy checks this structurally, signatures included. isinstance below only
    # checks that the member NAMES exist, so it cannot stand in for this.
    return repository


def test_repository_satisfies_the_protocol() -> None:
    repository = SqlAlchemyDiscoveryRepository(session=None)  # type: ignore[arg-type]
    assert isinstance(repository, DiscoveryRepository)
    assert _conforms(repository) is repository
```

Add these to the imports at the top of that file:

```python
from episignal_backend.ingestion.protocol import DiscoveryRepository
from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository
```

Run: `uv run pytest packages/backend/tests/test_discovery_repository.py -v`

Expected: PASS, 8 tests.

- [ ] **Step 6: Commit**

```bash
git add packages/backend/src/episignal_backend/ingestion/repository.py packages/backend/tests/test_discovery_repository.py
git commit -m "feat: store discovered signals and register publishers"
```

---

### Task 15: Add the configuration and the runner command

**Files:**
- Modify: `packages/backend/src/episignal_backend/config.py`
- Create: `packages/backend/src/episignal_backend/discover_runner.py`
- Modify: `package.json`
- Modify: `apps/api/.env.example`
- Test: `packages/backend/tests/test_config.py`, `packages/backend/tests/test_discover_runner.py`

- [ ] **Step 1: Write the failing config test**

Append to `packages/backend/tests/test_config.py`:

```python
def test_gdelt_settings_have_working_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "EPISIGNAL_DATABASE_URL", "postgresql+psycopg://user:pass@host:5432/database"
    )
    settings = Settings()  # type: ignore[call-arg]
    assert settings.gdelt_poll_interval_minutes == 15
    assert settings.gdelt_query_window_minutes == 20
    assert settings.gdelt_max_articles_per_run == 200
    assert settings.gdelt_request_delay_seconds == 5.0
    assert settings.gdelt_article_delay_seconds == 1.0


def test_the_query_window_must_cover_the_poll_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "EPISIGNAL_DATABASE_URL", "postgresql+psycopg://user:pass@host:5432/database"
    )
    monkeypatch.setenv("EPISIGNAL_GDELT_POLL_INTERVAL_MINUTES", "30")
    monkeypatch.setenv("EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES", "20")
    # A window narrower than the interval opens a gap no later run ever revisits.
    with pytest.raises(ValidationError, match="window"):
        Settings()  # type: ignore[call-arg]
```

Ensure `pytest` and `ValidationError` are imported at the top of that file; add
`from pydantic import ValidationError` if it is not already there.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_config.py -v`

Expected: FAIL with `AttributeError` on `gdelt_poll_interval_minutes`.

- [ ] **Step 3: Extend the settings**

In `packages/backend/src/episignal_backend/config.py`, add `model_validator` to
the pydantic import:

```python
from pydantic import BeforeValidator, Field, SecretStr, field_validator, model_validator
```

Add these fields to `Settings`, after `log_level`:

```python
    gdelt_poll_interval_minutes: int = Field(default=15, ge=1, le=1440)
    gdelt_query_window_minutes: int = Field(default=20, ge=1, le=10080)
    gdelt_max_articles_per_run: int = Field(default=200, ge=1, le=5000)
    gdelt_request_delay_seconds: float = Field(default=5.0, ge=0.0, le=60.0)
    gdelt_article_delay_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    gdelt_article_timeout_seconds: float = Field(default=15.0, ge=1.0, le=120.0)
    gdelt_user_agent: str = "EpiSignal/0.1 (+https://episignal.org)"
```

Add this validator to `Settings`:

```python
    @model_validator(mode="after")
    def window_covers_the_interval(self) -> "Settings":
        # A window narrower than the polling interval leaves articles published
        # in the gap undiscovered by every run, which no retry ever repairs.
        if self.gdelt_query_window_minutes < self.gdelt_poll_interval_minutes:
            raise ValueError(
                "EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES must cover "
                "EPISIGNAL_GDELT_POLL_INTERVAL_MINUTES"
            )
        return self
```

- [ ] **Step 4: Run the config test**

Run: `uv run pytest packages/backend/tests/test_config.py -v`

Expected: PASS.

- [ ] **Step 5: Write the failing runner test**

Create `packages/backend/tests/test_discover_runner.py`:

```python
import pytest

from episignal_backend.discover_runner import main, parse_arguments


def test_parses_an_explicit_window() -> None:
    assert parse_arguments(["--window-minutes", "45"]).window_minutes == 45


def test_parses_an_explicit_cap() -> None:
    assert parse_arguments(["--max-articles", "10"]).max_articles == 10


def test_defaults_come_from_configuration() -> None:
    arguments = parse_arguments([])
    assert arguments.window_minutes is None
    assert arguments.max_articles is None


def test_a_failure_prints_no_detail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode() -> None:
        raise RuntimeError("postgresql://user:hunter2@host/db is unreachable")

    monkeypatch.setattr("episignal_backend.discover_runner._run", lambda _: explode())
    assert main([]) == 1
    captured = capsys.readouterr()
    # The connection string must never reach a console or a log scrape.
    assert "hunter2" not in captured.err
    assert "hunter2" not in captured.out
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_discover_runner.py -v`

Expected: FAIL with `ModuleNotFoundError` for `discover_runner`.

- [ ] **Step 7: Write the runner**

Create `packages/backend/src/episignal_backend/discover_runner.py`:

```python
"""Entry point for `pnpm discover:gdelt`.

Counts only. Failure detail is kept out of stdout because the connection string
and page bodies would otherwise reach the console.

One run is one polling tick. Scheduling lives outside this repository, so the
interval is configuration this command reads rather than a loop it owns.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.ingestion.discovery import DiscoveryResult, run_discovery
from episignal_backend.ingestion.gdelt.api import GdeltDocClient
from episignal_backend.ingestion.gdelt.article import ArticleFetcher
from episignal_backend.ingestion.gdelt.connector import GdeltConnector
from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository


@dataclass(frozen=True)
class Arguments:
    window_minutes: int | None
    max_articles: int | None


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="discover", description="Discover articles through GDELT."
    )
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=None,
        help="Search window in minutes. Defaults to EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES.",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=None,
        help="Pages to retrieve this run. Defaults to EPISIGNAL_GDELT_MAX_ARTICLES_PER_RUN.",
    )
    parsed = parser.parse_args(list(argv))
    return Arguments(window_minutes=parsed.window_minutes, max_articles=parsed.max_articles)


def _run(arguments: Arguments) -> DiscoveryResult:
    settings = get_settings()
    connector = GdeltConnector(
        search=GdeltDocClient(),
        fetcher=ArticleFetcher(
            delay_seconds=settings.gdelt_article_delay_seconds,
            user_agent=settings.gdelt_user_agent,
            timeout_seconds=settings.gdelt_article_timeout_seconds,
        ),
    )
    with session_scope() as session:
        return run_discovery(
            SqlAlchemyDiscoveryRepository(session),
            connector,
            window_minutes=arguments.window_minutes or settings.gdelt_query_window_minutes,
            max_articles=arguments.max_articles or settings.gdelt_max_articles_per_run,
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        result = _run(arguments)
    except Exception:
        print(
            "Discovery failed before completing. Check GDELT and the database.",
            file=sys.stderr,
        )
        return 1

    if result.rules_run == 0:
        print("No active query rules. Run pnpm db:seed first.", file=sys.stderr)
        return 1

    print(
        f"rules={result.rules_run} rules_failed={result.rules_failed} "
        f"discovered={result.discovered} duplicate={result.duplicate} "
        f"deferred={result.deferred} stored={result.stored} "
        f"needs_review={result.needs_review} failed={result.failed}"
    )
    return 1 if result.rules_failed == result.rules_run and result.rules_run else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 8: Add the script and document the settings**

In `package.json`, add after `"db:seed"`:

```json
    "discover:gdelt": "uv run --package episignal-backend python -m episignal_backend.discover_runner",
```

Append to `apps/api/.env.example`:

```text
# GDELT discovery. The poll interval is read by whatever scheduler calls
# `pnpm discover:gdelt`; the query window must cover it so no gap goes unsearched.
EPISIGNAL_GDELT_POLL_INTERVAL_MINUTES=15
EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES=20
EPISIGNAL_GDELT_MAX_ARTICLES_PER_RUN=200
EPISIGNAL_GDELT_REQUEST_DELAY_SECONDS=5.0
EPISIGNAL_GDELT_ARTICLE_DELAY_SECONDS=1.0
EPISIGNAL_GDELT_ARTICLE_TIMEOUT_SECONDS=15.0
EPISIGNAL_GDELT_USER_AGENT=EpiSignal/0.1 (+https://episignal.org)
```

- [ ] **Step 9: Run the whole suite and the type checker**

Run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy apps/api/src packages/backend/src
```

Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add packages/backend/src/episignal_backend/config.py packages/backend/src/episignal_backend/discover_runner.py packages/backend/tests/test_config.py packages/backend/tests/test_discover_runner.py package.json apps/api/.env.example
git commit -m "feat: add the GDELT discovery command and its configuration"
```

---

### Task 16: Verify against the live API and the live database

Everything before this ran against fixtures. This task confirms the two
assumptions the design flagged as unverified, and proves the vertical slice end
to end.

**Files:**
- Modify: `database/seeds/gdelt_queries.json` (only if Step 2 succeeds)
- Modify: `docs/superpowers/specs/2026-08-27-gdelt-discovery-design.md`
- Modify: `README.md`

- [ ] **Step 1: Verify the live API still matches the fixture**

Run:

```bash
curl -s "https://api.gdeltproject.org/api/v2/doc/doc?query=cholera&mode=ArtList&format=json&timespan=1d&maxrecords=3&sort=datedesc"
```

Expected: a JSON object with an `articles` key whose entries carry `url`,
`title`, `seendate`, `domain`, `language`, `sourcecountry`.

If the field set has changed, stop and report it. `api.py` and the fixture both
depend on this shape.

**GDELT rate-limits aggressively.** Wait at least 30 seconds between the calls
in this task, or later ones will be refused at the transport layer.

- [ ] **Step 2: Verify the two unverified assumptions**

Run, waiting 30 seconds between each:

```bash
curl -s "https://api.gdeltproject.org/api/v2/doc/doc?query=cholera&mode=ArtList&format=json&timespan=15min&maxrecords=10"
```

```bash
curl -s "https://api.gdeltproject.org/api/v2/doc/doc?query=cholera%20sourcelang:vietnamese&mode=ArtList&format=json&timespan=1d&maxrecords=10"
```

Record in the design document, under "Not yet verified", which of
`timespan=15min` and `sourcelang:` the API accepted, and change the heading to
"Verified on 2026-08-27" for whichever now holds.

Only if `sourcelang:` works, add language-restricted rules for the highest-value
local languages to `database/seeds/gdelt_queries.json`, for example:

```json
  { "rule_group": "syndromic", "query": "\"unknown illness\" sourcelang:vietnamese", "label": "Unknown illness (Vietnamese)", "language": "vi" },
  { "rule_group": "syndromic", "query": "\"unknown illness\" sourcelang:thai", "label": "Unknown illness (Thai)", "language": "th" }
```

If it does not work, leave the seed as it is and say so in the design document.
Do not invent a syntax.

- [ ] **Step 3: Migrate and seed the live database**

These act on the real database named by `apps/api/.env`.

```bash
npx --yes pnpm@11.19.0 db:migrate
npx --yes pnpm@11.19.0 db:seed
```

Expected: the migration reports `20260827_0003`, and seeding prints
`diseases=<n> sources=<n> query_rules=56`.

- [ ] **Step 4: Run one discovery**

```bash
npx --yes pnpm@11.19.0 discover:gdelt -- --max-articles 5
```

Expected: a line of counts, for example
`rules=56 rules_failed=0 discovered=... duplicate=0 deferred=... stored=... needs_review=... failed=0`.

- [ ] **Step 5: Confirm the vertical slice in the database**

Run this query against the live database:

```sql
SELECT s.title,
       so.name        AS publisher,
       so.domain,
       s.url,
       s.published_at,
       s.published_at_offset_minutes,
       s.first_seen_at,
       s.retrieved_at,
       s.gdelt_seen_at,
       s.discovered_via,
       s.processing_status,
       r.label        AS query_rule
FROM signals s
JOIN sources so ON so.id = s.source_id
LEFT JOIN gdelt_query_rules r ON r.id = s.query_rule_id
WHERE s.discovered_via = 'gdelt'
ORDER BY s.first_seen_at DESC
LIMIT 10;
```

Confirm every one of these, and record the result:

- `publisher` is a real outlet name or its domain, never "GDELT";
- `url` opens the original article in a browser;
- `published_at`, `first_seen_at`, `retrieved_at`, and `gdelt_seen_at` hold four
  distinct meanings, and `published_at` is either a real publication time or NULL;
- `discovered_via` is `gdelt`;
- `query_rule` names the rule that found it.

- [ ] **Step 6: Confirm official ingestion is unharmed**

```bash
npx --yes pnpm@11.19.0 ingest:who
```

Expected: it still runs, and every WHO signal keeps `discovered_via = 'direct'`:

```sql
SELECT discovered_via, count(*) FROM signals GROUP BY discovered_via;
```

- [ ] **Step 7: Record the passing gate**

Append a "Verification" section to
`docs/superpowers/specs/2026-08-27-gdelt-discovery-design.md` recording the
date, the counts from Step 4, the outcome of Step 2, and the confirmation from
Step 5.

Update the "Current scope" section of `README.md` to say that GDELT discovery
runs, that discovered signals keep their publisher and original URL, and that
they are early signals rather than confirmed events.

- [ ] **Step 8: Commit**

```bash
git add docs/superpowers/specs/2026-08-27-gdelt-discovery-design.md README.md database/seeds/gdelt_queries.json
git commit -m "docs: record the passing gate for GDELT discovery"
```

---

## Definition of done for this sub-project

Check each against the design document before declaring the slice complete.

- [ ] GDELT polling runs from one command a scheduler can call.
- [ ] Queries are configurable in the database without a code change.
- [ ] Every signal keeps its actual publisher and its original URL.
- [ ] `published_at`, `first_seen_at`, `retrieved_at`, and `gdelt_seen_at` are stored separately and never substituted for one another.
- [ ] A missing publication time is NULL, not a guess.
- [ ] Already-seen URLs cost no page fetch.
- [ ] A failed page fetch is stored as `needs_review`, never dropped silently.
- [ ] No GDELT signal is marked `officially_confirmed`.
- [ ] WHO and ECDC ingestion is unchanged and still passes its tests.
- [ ] `uv run pytest`, `uv run ruff check .`, and `uv run mypy apps/api/src packages/backend/src` all pass.

## Known follow-on work, deliberately not in this plan

- **Retrying `needs_review` stubs** is designed in the spec under "Signals awaiting retrieval" but has no task here. It needs a reader of stub rows and an in-place promotion path, which is a self-contained slice best done once real stubs exist to measure. Open it as the first task of sub-project B.
- **Syndication deduplication** is sub-project B. The `gdelt_artlist.json` fixture deliberately keeps four copies of one story as its test material.
- **The Prettier line-ending failure** on `main` blocks `pnpm verify` and predates this work.

## Primary references

- `docs/superpowers/specs/2026-08-27-gdelt-discovery-design.md`
- `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md`
- `docs/superpowers/plans/2026-08-26-who-don-ingestion.md` — the plan this one mirrors in structure.
- GDELT DOC 2.0 API: <https://api.gdeltproject.org/api/v2/doc/doc>
