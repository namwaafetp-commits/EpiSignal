# WHO Disease Outbreak News Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest WHO Disease Outbreak News documents into the `signals` table, keyed to their source, so that re-running never duplicates a document and a revised document is stored as an additional version rather than overwriting the original.

**Architecture:** A `SourceConnector` fetches and normalizes documents; a `SignalRepository` stores them. `pipeline.py` depends on those two Protocols only, so every ingestion decision is unit-tested with in-memory fakes, no database and no network. `who_don.py` is the only module that opens a socket, and its `normalize` is a pure function tested against a committed JSON fixture.

**Tech Stack:** Python 3.12, uv, httpx, Pydantic 2, SQLAlchemy 2, Alembic, pytest, Ruff, mypy strict.

**Design:** `docs/superpowers/specs/2026-08-26-who-don-ingestion-design.md`

---

## File Structure

```text
database/migrations/versions/20260826_0002_signal_versions.py   Relax the URL constraint
packages/backend/src/episignal_backend/models/signal.py         Composite uniqueness
packages/backend/src/episignal_backend/ingestion/__init__.py    Package marker
packages/backend/src/episignal_backend/ingestion/urls.py        canonicalize_url (pure)
packages/backend/src/episignal_backend/ingestion/fingerprint.py content_hash (pure)
packages/backend/src/episignal_backend/ingestion/documents.py   RawDocument, NormalizedSignal
packages/backend/src/episignal_backend/ingestion/protocol.py    SourceConnector, SignalRepository
packages/backend/src/episignal_backend/ingestion/who_don.py     WHO connector
packages/backend/src/episignal_backend/ingestion/repository.py  SQLAlchemy repository
packages/backend/src/episignal_backend/ingestion/pipeline.py    run_ingestion
packages/backend/src/episignal_backend/ingest_runner.py         CLI entry point
packages/backend/tests/fixtures/who_don_sample.json             Committed API response
database/seeds/sources.json                                     Correct the WHO URL
packages/backend/src/episignal_backend/schema_check.py          Report signal counts
package.json                                                    ingest:who script
```

Every module is behaviour-bearing and follows red-green-refactor. The JSON fixture and the package marker are data, not behaviour.

Run every command from the repository root, `D:\Projects\Side Project\EpiSignal`.

---

### Task 1: Version signals by content hash

A revised WHO document keeps its URL, so URL alone can no longer be the identity of a signal.

**Files:**
- Modify: `packages/backend/tests/test_models.py`
- Modify: `packages/backend/src/episignal_backend/models/signal.py`
- Modify: `apps/api/tests/test_migrations.py`
- Create: `database/migrations/versions/20260826_0002_signal_versions.py`

- [x] **Step 1: Replace the URL uniqueness test**

In `packages/backend/tests/test_models.py`, delete this test entirely:

```python
def test_signal_original_url_is_unique_and_required() -> None:
    url = Base.metadata.tables["signals"].c.url
    assert url.nullable is False
    assert url.unique is True
```

Add this in its place:

```python
def test_signal_versions_are_unique_by_url_and_content_hash() -> None:
    table = Base.metadata.tables["signals"]
    assert table.c.url.nullable is False
    assert table.c.url.unique is not True
    constraint = next(
        item
        for item in table.constraints
        if getattr(item, "name", None) == "uq_signals_url_content_hash"
    )
    assert [column.name for column in constraint.columns] == ["url", "content_hash"]
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_models.py -k versions -v`

Expected: FAIL with `StopIteration`, because no constraint is named `uq_signals_url_content_hash` yet.

- [x] **Step 3: Change the model**

In `packages/backend/src/episignal_backend/models/signal.py`, add `UniqueConstraint` to the existing `sqlalchemy` import list, so it reads:

```python
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
```

Add the constraint as the first entry of `__table_args__`:

```python
    __table_args__ = (
        UniqueConstraint("url", "content_hash", name="uq_signals_url_content_hash"),
        CheckConstraint(
            "relevance_score >= 0 AND relevance_score <= 1", name="relevance_score_range"
        ),
        Index("ix_signals_source_id", "source_id"),
        Index("ix_signals_published_at", "published_at"),
        Index("ix_signals_canonical_url", "canonical_url"),
        Index("ix_signals_content_hash", "content_hash"),
        Index("ix_signals_processing_status", "processing_status"),
    )
```

Change the `url` column to drop `unique=True`:

```python
    url: Mapped[str] = mapped_column(Text, nullable=False)
```

The constraint carries an explicit name because the metadata naming convention
would otherwise derive `uq_signals_url` from the first column and collide with
the constraint this migration drops.

- [x] **Step 4: Run the test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_models.py -v`

Expected: PASS, 9 tests.

- [x] **Step 5: Update the migration head test**

In `apps/api/tests/test_migrations.py`, change the head assertion:

```python
def test_migrations_have_one_linear_head() -> None:
    root = Path(__file__).parents[3]
    config = Config(root / "database" / "alembic.ini")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["20260826_0002"]
```

Then add this test at the end of the same file:

```python
def test_second_revision_versions_signals_by_content_hash() -> None:
    sql = render_offline("upgrade", "head")
    assert "uq_signals_url_content_hash" in sql
    assert "drop constraint uq_signals_url" in sql
```

- [x] **Step 6: Run the migration tests to verify they fail**

Run: `uv run pytest apps/api/tests/test_migrations.py -v`

Expected: FAIL. `test_migrations_have_one_linear_head` reports `['20260826_0001'] != ['20260826_0002']` because the second revision does not exist yet.

- [x] **Step 7: Write the migration**

Create `database/migrations/versions/20260826_0002_signal_versions.py`:

```python
"""version signals by content hash

Revision ID: 20260826_0002
Revises: 20260826_0001
Create Date: 2026-08-26

A revised source document keeps its URL, so URL alone cannot identify a signal.
Identity becomes the pair of URL and content hash, which lets a revision be
stored as an additional row instead of overwriting the text an earlier
observation was extracted from.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260826_0002"
down_revision: str | None = "20260826_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_signals_url", "signals", type_="unique")
    op.create_unique_constraint(
        "uq_signals_url_content_hash", "signals", ["url", "content_hash"]
    )


def downgrade() -> None:
    # This fails when several versions of one URL exist, which is correct:
    # discarding stored evidence to satisfy a narrower constraint would be worse
    # than a failed downgrade.
    op.drop_constraint("uq_signals_url_content_hash", "signals", type_="unique")
    op.create_unique_constraint("uq_signals_url", "signals", ["url"])
```

- [x] **Step 8: Run the migration tests to verify they pass**

Run: `uv run pytest apps/api/tests/test_migrations.py -v`

Expected: PASS, 4 tests.

- [x] **Step 9: Run every check**

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/backend/src apps/api/src
```

Expected: every test passes; Ruff and mypy clean.

- [x] **Step 10: Commit**

```bash
git add packages/backend database/migrations apps/api/tests/test_migrations.py
git commit -m "feat: version signals by content hash"
```

---

### Task 2: Canonicalize document URLs

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/__init__.py`
- Create: `packages/backend/tests/test_ingestion_urls.py`
- Create: `packages/backend/src/episignal_backend/ingestion/urls.py`

- [x] **Step 1: Write the failing tests**

Create `packages/backend/tests/test_ingestion_urls.py`:

```python
import pytest
from episignal_backend.ingestion.urls import canonicalize_url

ITEM = "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (ITEM, ITEM),
        (f"{ITEM}#summary", ITEM),
        (f"{ITEM}/", ITEM),
        (f"{ITEM}?utm_source=newsletter&utm_campaign=x", ITEM),
        (f"{ITEM}?gclid=abc&fbclid=def", ITEM),
        ("HTTPS://WWW.WHO.INT/emergencies", "https://www.who.int/emergencies"),
        (f"{ITEM}?b=2&a=1", f"{ITEM}?a=1&b=2"),
        ("https://www.who.int/", "https://www.who.int/"),
    ],
)
def test_canonicalize_url_removes_noise_without_changing_identity(
    raw: str, expected: str
) -> None:
    assert canonicalize_url(raw) == expected


def test_canonicalize_url_preserves_path_case() -> None:
    assert canonicalize_url(ITEM).endswith("2026-DON615")


def test_canonicalize_url_keeps_meaningful_query_parameters() -> None:
    assert canonicalize_url(f"{ITEM}?page=2") == f"{ITEM}?page=2"


def test_canonicalize_url_is_idempotent() -> None:
    once = canonicalize_url(f"{ITEM}/?utm_source=x#top")
    assert canonicalize_url(once) == once
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/backend/tests/test_ingestion_urls.py -v`

Expected: FAIL at collection with `ModuleNotFoundError: No module named 'episignal_backend.ingestion'`.

- [x] **Step 3: Create the package marker**

Create `packages/backend/src/episignal_backend/ingestion/__init__.py` containing exactly one line:

```python
"""Source ingestion: fetch documents, normalize them, store them once."""
```

- [x] **Step 4: Implement canonicalize_url**

Create `packages/backend/src/episignal_backend/ingestion/urls.py`:

```python
"""URL canonicalization.

Two URLs that differ only by tracking parameters, a fragment, host casing or a
trailing slash name the same document. Path case is preserved because document
identifiers such as `2026-DON615` are case-sensitive on the origin server.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMETERS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
    }
)


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    parameters = sorted(
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if name.lower() not in TRACKING_PARAMETERS
    )
    path = parsed.path if parsed.path == "/" else parsed.path.rstrip("/")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            urlencode(parameters),
            "",
        )
    )
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_ingestion_urls.py -v`

Expected: PASS, 11 tests.

- [x] **Step 6: Commit**

```bash
git add packages/backend
git commit -m "feat: canonicalize source document URLs"
```

---

### Task 3: Fingerprint document content

**Files:**
- Create: `packages/backend/tests/test_ingestion_fingerprint.py`
- Create: `packages/backend/src/episignal_backend/ingestion/fingerprint.py`

- [x] **Step 1: Write the failing tests**

Create `packages/backend/tests/test_ingestion_fingerprint.py`:

```python
from episignal_backend.ingestion.fingerprint import content_hash


def test_content_hash_fits_the_signal_column() -> None:
    assert len(content_hash("Ebola - DRC", "4665 confirmed cases.")) == 64


def test_content_hash_ignores_whitespace_only_differences() -> None:
    assert content_hash("Ebola - DRC", "4665  confirmed\n cases.") == content_hash(
        "Ebola - DRC", "4665 confirmed cases."
    )


def test_content_hash_changes_when_a_reported_number_changes() -> None:
    assert content_hash("Ebola - DRC", "4665 confirmed cases.") != content_hash(
        "Ebola - DRC", "4670 confirmed cases."
    )


def test_content_hash_changes_when_the_title_changes() -> None:
    assert content_hash("Ebola - DRC", "same body") != content_hash(
        "Ebola - Uganda", "same body"
    )


def test_content_hash_does_not_confuse_title_and_body_boundaries() -> None:
    assert content_hash("a", "b") != content_hash("a b", "")
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/backend/tests/test_ingestion_fingerprint.py -v`

Expected: FAIL at collection with `ModuleNotFoundError: No module named 'episignal_backend.ingestion.fingerprint'`.

- [x] **Step 3: Implement content_hash**

Create `packages/backend/src/episignal_backend/ingestion/fingerprint.py`:

```python
"""Content fingerprinting.

The hash decides whether a retrieved document is a new version of one already
stored, so it must ignore reformatting and react to any change in wording or in
a reported number. The digest is 64 hex characters, exactly the width of
`signals.content_hash`.
"""

import hashlib

SEPARATOR = "\x1f"


def _collapse(value: str) -> str:
    return " ".join(value.split())


def content_hash(title: str, body: str) -> str:
    payload = f"{_collapse(title)}{SEPARATOR}{_collapse(body)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

The unit separator keeps the title and body fields distinct, so a title ending
in a word the body begins with cannot collide with a different split of the same
characters.

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_ingestion_fingerprint.py -v`

Expected: PASS, 5 tests.

- [x] **Step 5: Commit**

```bash
git add packages/backend
git commit -m "feat: fingerprint document content"
```

---

### Task 4: Define the ingestion contracts

**Files:**
- Create: `packages/backend/tests/test_ingestion_documents.py`
- Create: `packages/backend/src/episignal_backend/ingestion/documents.py`
- Create: `packages/backend/src/episignal_backend/ingestion/protocol.py`

- [x] **Step 1: Write the failing tests**

Create `packages/backend/tests/test_ingestion_documents.py`:

```python
from datetime import UTC, datetime

import pytest
from episignal_backend.db.types import ProcessingStatus, SignalType
from episignal_backend.ingestion.documents import NormalizedSignal, RawDocument
from pydantic import ValidationError

MOMENT = datetime(2026, 8, 14, 15, 38, 29, tzinfo=UTC)


def valid_signal(**overrides: object) -> NormalizedSignal:
    fields: dict[str, object] = {
        "external_id": "2026-DON615",
        "url": "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615",
        "canonical_url": (
            "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615"
        ),
        "title": "Ebola disease - Democratic Republic of the Congo",
        "raw_text": "4665 confirmed cases, including 2184 deaths.",
        "published_at": MOMENT,
        "retrieved_at": MOMENT,
        "language": "en",
        "content_hash": "a" * 64,
    }
    fields.update(overrides)
    return NormalizedSignal(**fields)  # type: ignore[arg-type]


def test_normalized_signal_defaults_to_unprocessed_state() -> None:
    signal = valid_signal()
    assert signal.signal_type is SignalType.UNKNOWN
    assert signal.processing_status is ProcessingStatus.FETCHED


def test_normalized_signal_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        valid_signal(summary="a summary the extraction slice has not produced")


def test_normalized_signal_rejects_a_naive_published_at() -> None:
    with pytest.raises(ValidationError):
        valid_signal(published_at=datetime(2026, 8, 14, 15, 38, 29))


def test_normalized_signal_rejects_an_empty_title() -> None:
    with pytest.raises(ValidationError):
        valid_signal(title="   ")


def test_normalized_signal_is_frozen() -> None:
    signal = valid_signal()
    with pytest.raises(ValidationError):
        signal.title = "changed"  # type: ignore[misc]


def test_raw_document_keeps_the_untouched_source_payload() -> None:
    document = RawDocument(payload={"Title": "x", "UrlName": "y"}, retrieved_at=MOMENT)
    assert document.payload["UrlName"] == "y"
    assert document.retrieved_at == MOMENT
```

- [x] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/backend/tests/test_ingestion_documents.py -v`

Expected: FAIL at collection with `ModuleNotFoundError: No module named 'episignal_backend.ingestion.documents'`.

- [x] **Step 3: Implement the document contracts**

Create `packages/backend/src/episignal_backend/ingestion/documents.py`:

```python
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
```

- [x] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_ingestion_documents.py -v`

Expected: PASS, 6 tests.

- [x] **Step 5: Implement the Protocols**

Create `packages/backend/src/episignal_backend/ingestion/protocol.py`:

```python
"""The two boundaries the pipeline depends on.

`pipeline.py` imports these Protocols and nothing else, so every ingestion
decision is testable with in-memory fakes: no database, no network, no
credentials.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from episignal_backend.ingestion.documents import NormalizedSignal, RawDocument


@runtime_checkable
class SourceConnector(Protocol):
    source_name: str

    def fetch(self, since: datetime) -> Sequence[RawDocument]: ...

    def normalize(self, document: RawDocument) -> NormalizedSignal: ...


@runtime_checkable
class SignalRepository(Protocol):
    def source_id(self, name: str) -> UUID | None: ...

    def latest_published_at(self, source_id: UUID) -> datetime | None: ...

    def exists(self, url: str, content_hash: str) -> bool: ...

    def add(self, signal: NormalizedSignal, source_id: UUID) -> None: ...

    def activate(self, source_id: UUID) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
```

- [x] **Step 6: Run the checks**

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy packages/backend/src apps/api/src
```

Expected: all tests pass; Ruff and mypy clean.

- [x] **Step 7: Commit**

```bash
git add packages/backend
git commit -m "feat: define ingestion contracts and boundaries"
```

---

### Task 5: Normalize WHO documents

**Files:**
- Create: `packages/backend/tests/fixtures/who_don_sample.json`
- Create: `packages/backend/tests/test_who_don_normalize.py`
- Create: `packages/backend/src/episignal_backend/ingestion/who_don.py`

- [x] **Step 1: Add the fixture**

Create `packages/backend/tests/fixtures/who_don_sample.json`. This is a trimmed
capture of a real WHO API response, keeping the fields the connector reads:

```json
{
  "value": [
    {
      "Id": "3a950a6c-8e9a-4d58-b8db-6840bd02db92",
      "DonId": "2026-DON615",
      "UrlName": "2026-DON615",
      "ItemDefaultUrl": "/2026-DON615",
      "Title": "Ebola disease caused by Bundibugyo virus  -  Democratic Republic of the Congo",
      "PublicationDate": "2026-08-14T00:00:00Z",
      "PublicationDateAndTime": "2026-08-14T15:38:29Z",
      "LastModified": "2026-08-15T09:02:11Z",
      "Overview": "<p>On 14 August 2026, the Ministry of Health reported an outbreak.</p>",
      "Epidemiology": "<p>As of 14 August, <strong>4665</strong> confirmed cases, including 2184 deaths, have been reported.</p>",
      "Assessment": "<p>WHO assesses the risk at national level as high.</p>",
      "Advice": "<p>WHO advises against travel restrictions.</p>",
      "Response": "<p>Vaccination &amp; contact tracing are ongoing.</p>"
    },
    {
      "Id": "19668b4d-5e4f-45bf-94d5-4e2ebcb5a67d",
      "DonId": "2026-DON614",
      "UrlName": "2026-DON614",
      "ItemDefaultUrl": "/2026-DON614",
      "Title": "Ebola disease caused by Bundibugyo virus - Democratic Republic of the Congo",
      "PublicationDate": "2026-08-01T00:00:00Z",
      "PublicationDateAndTime": "2026-08-01T10:13:28Z",
      "LastModified": "2026-08-01T10:13:28Z",
      "Overview": "<p>An earlier update on the same outbreak.</p>",
      "Epidemiology": "",
      "Assessment": null,
      "Advice": "<p>No change to advice.</p>",
      "Response": ""
    }
  ]
}
```

- [x] **Step 2: Write the failing tests**

Create `packages/backend/tests/test_who_don_normalize.py`:

```python
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from episignal_backend.db.types import ProcessingStatus, SignalType
from episignal_backend.ingestion.documents import RawDocument
from episignal_backend.ingestion.who_don import WhoDonConnector

FIXTURE = Path(__file__).parent / "fixtures" / "who_don_sample.json"
RETRIEVED = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def documents() -> list[RawDocument]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [RawDocument(payload=item, retrieved_at=RETRIEVED) for item in payload["value"]]


def test_normalize_builds_the_public_document_url() -> None:
    signal = WhoDonConnector().normalize(documents()[0])
    assert signal.url == (
        "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615"
    )
    assert signal.canonical_url == signal.url


def test_normalize_uses_the_don_id_as_the_external_identifier() -> None:
    assert WhoDonConnector().normalize(documents()[0]).external_id == "2026-DON615"


def test_normalize_collapses_whitespace_in_the_title() -> None:
    signal = WhoDonConnector().normalize(documents()[0])
    assert signal.title == (
        "Ebola disease caused by Bundibugyo virus - Democratic Republic of the Congo"
    )


def test_normalize_joins_every_section_and_strips_markup() -> None:
    text = WhoDonConnector().normalize(documents()[0]).raw_text
    assert "<p>" not in text
    assert "<strong>" not in text
    assert "4665 confirmed cases, including 2184 deaths" in text
    assert "WHO advises against travel restrictions." in text
    assert "Vaccination & contact tracing are ongoing." in text


def test_normalize_skips_empty_and_missing_sections() -> None:
    text = WhoDonConnector().normalize(documents()[1]).raw_text
    assert text == "An earlier update on the same outbreak.\n\nNo change to advice."


def test_normalize_reads_the_publication_timestamp_as_utc() -> None:
    signal = WhoDonConnector().normalize(documents()[0])
    assert signal.published_at == datetime(2026, 8, 14, 15, 38, 29, tzinfo=UTC)
    assert signal.retrieved_at == RETRIEVED


def test_normalize_leaves_the_document_unprocessed() -> None:
    signal = WhoDonConnector().normalize(documents()[0])
    assert signal.processing_status is ProcessingStatus.FETCHED
    assert signal.signal_type is SignalType.UNKNOWN
    assert signal.language == "en"


def test_normalize_produces_a_stable_content_hash() -> None:
    connector = WhoDonConnector()
    first = connector.normalize(documents()[0])
    second = connector.normalize(documents()[0])
    assert first.content_hash == second.content_hash
    assert len(first.content_hash) == 64


def test_normalize_rejects_a_document_without_a_url_name() -> None:
    broken = RawDocument(payload={"Title": "x"}, retrieved_at=RETRIEVED)
    with pytest.raises(ValueError, match="UrlName"):
        WhoDonConnector().normalize(broken)


def test_connector_names_the_seeded_source() -> None:
    assert WhoDonConnector().source_name == "WHO Disease Outbreak News"
```

- [x] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest packages/backend/tests/test_who_don_normalize.py -v`

Expected: FAIL at collection with `ModuleNotFoundError: No module named 'episignal_backend.ingestion.who_don'`.

- [x] **Step 4: Implement normalization**

Create `packages/backend/src/episignal_backend/ingestion/who_don.py`:

```python
"""WHO Disease Outbreak News connector.

WHO publishes DONs through an OData JSON API rather than a feed. `normalize` is
a pure function of one payload, so it is tested against a committed fixture with
no network access.
"""

from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser

from episignal_backend.ingestion.documents import NormalizedSignal, RawDocument
from episignal_backend.ingestion.fingerprint import content_hash
from episignal_backend.ingestion.urls import canonicalize_url

SOURCE_NAME = "WHO Disease Outbreak News"
ITEM_URL_TEMPLATE = "https://www.who.int/emergencies/disease-outbreak-news/item/{url_name}"
SECTION_FIELDS = ("Overview", "Epidemiology", "Assessment", "Advice", "Response")
BLOCK_TAGS = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in BLOCK_TAGS:
            self.parts.append(" ")


def strip_html(value: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(value)
    extractor.close()
    return " ".join(unescape("".join(extractor.parts)).split())


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class WhoDonConnector:
    source_name = SOURCE_NAME

    def normalize(self, document: RawDocument) -> NormalizedSignal:
        payload = document.payload

        url_name = str(payload.get("UrlName") or "").strip()
        if not url_name:
            raise ValueError("WHO document has no UrlName")

        url = ITEM_URL_TEMPLATE.format(url_name=url_name)
        title = str(payload.get("Title") or "")
        sections = [strip_html(str(payload.get(field) or "")) for field in SECTION_FIELDS]
        raw_text = "\n\n".join(section for section in sections if section)
        external_id = str(payload.get("DonId") or "").strip() or None

        return NormalizedSignal(
            external_id=external_id,
            url=url,
            canonical_url=canonicalize_url(url),
            title=title,
            raw_text=raw_text,
            published_at=parse_utc(str(payload["PublicationDateAndTime"])),
            retrieved_at=document.retrieved_at,
            language="en",
            content_hash=content_hash(title, raw_text),
        )
```

- [x] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_who_don_normalize.py -v`

Expected: PASS, 10 tests.

- [x] **Step 6: Commit**

```bash
git add packages/backend
git commit -m "feat: normalize WHO outbreak news documents"
```

---

### Task 6: Fetch WHO documents over HTTP

**Files:**
- Modify: `packages/backend/pyproject.toml`
- Create: `packages/backend/tests/test_who_don_fetch.py`
- Modify: `packages/backend/src/episignal_backend/ingestion/who_don.py`

- [ ] **Step 1: Add the HTTP dependency**

In `packages/backend/pyproject.toml`, add `httpx` to `dependencies` so the list reads:

```toml
dependencies = [
  "geoalchemy2>=0.18,<1",
  "httpx>=0.28,<1",
  "pydantic-settings>=2.10,<3",
  "psycopg[binary]>=3.2,<4",
  "sqlalchemy>=2.0,<2.1",
]
```

Then run: `uv sync -q`

- [ ] **Step 2: Write the failing tests**

Create `packages/backend/tests/test_who_don_fetch.py`:

```python
from datetime import UTC, datetime

import httpx
import pytest
from episignal_backend.ingestion.who_don import PAGE_SIZE, WhoDonConnector

SINCE = datetime(2026, 5, 28, tzinfo=UTC)


def item(index: int) -> dict[str, object]:
    return {
        "UrlName": f"2026-DON{index}",
        "DonId": f"2026-DON{index}",
        "Title": f"Outbreak {index}",
        "PublicationDateAndTime": "2026-08-14T15:38:29Z",
        "Overview": "<p>Body</p>",
    }


def connector_for(handler: object, requests: list[httpx.Request]) -> WhoDonConnector:
    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)  # type: ignore[operator]

    client = httpx.Client(transport=httpx.MockTransport(record))
    return WhoDonConnector(client=client, sleep=lambda seconds: None)


def test_fetch_returns_one_raw_document_per_item() -> None:
    requests: list[httpx.Request] = []
    connector = connector_for(
        lambda request: httpx.Response(200, json={"value": [item(1), item(2)]}), requests
    )
    documents = connector.fetch(SINCE)
    assert len(documents) == 2
    assert documents[0].payload["DonId"] == "2026-DON1"
    assert documents[0].retrieved_at.tzinfo is not None


def test_fetch_filters_and_orders_by_publication_time() -> None:
    requests: list[httpx.Request] = []
    connector = connector_for(
        lambda request: httpx.Response(200, json={"value": []}), requests
    )
    connector.fetch(SINCE)
    query = requests[0].url.params
    assert query["$filter"] == "PublicationDateAndTime gt 2026-05-28T00:00:00Z"
    assert query["$orderby"] == "PublicationDateAndTime asc"
    assert query["$top"] == str(PAGE_SIZE)


def test_fetch_pages_until_a_short_page_arrives() -> None:
    requests: list[httpx.Request] = []
    pages = [
        {"value": [item(index) for index in range(PAGE_SIZE)]},
        {"value": [item(999)]},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages[len(requests) - 1])

    connector = connector_for(handler, requests)
    documents = connector.fetch(SINCE)
    assert len(documents) == PAGE_SIZE + 1
    assert requests[1].url.params["$skip"] == str(PAGE_SIZE)


def test_fetch_retries_a_server_error_then_succeeds() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if len(requests) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"value": [item(1)]})

    connector = connector_for(handler, requests)
    assert len(connector.fetch(SINCE)) == 1
    assert len(requests) == 3


def test_fetch_raises_after_exhausting_retries() -> None:
    requests: list[httpx.Request] = []
    connector = connector_for(lambda request: httpx.Response(503), requests)
    with pytest.raises(httpx.HTTPError):
        connector.fetch(SINCE)
    assert len(requests) == 3


def test_fetch_does_not_retry_a_client_error() -> None:
    requests: list[httpx.Request] = []
    connector = connector_for(lambda request: httpx.Response(404), requests)
    with pytest.raises(httpx.HTTPError):
        connector.fetch(SINCE)
    assert len(requests) == 1
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest packages/backend/tests/test_who_don_fetch.py -v`

Expected: FAIL at collection with `ImportError: cannot import name 'PAGE_SIZE'`.

- [ ] **Step 4: Implement fetching**

In `packages/backend/src/episignal_backend/ingestion/who_don.py`, extend the
imports at the top of the file:

```python
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from time import sleep as default_sleep
from typing import Any

import httpx

from episignal_backend.ingestion.documents import NormalizedSignal, RawDocument
from episignal_backend.ingestion.fingerprint import content_hash
from episignal_backend.ingestion.urls import canonicalize_url
```

Add these constants beside the existing ones:

```python
API_URL = "https://www.who.int/api/news/diseaseoutbreaknews"
PAGE_SIZE = 50
TIMEOUT_SECONDS = 20.0
MAX_ATTEMPTS = 3
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
```

Replace the `class WhoDonConnector:` header and add the fetch methods, keeping
the existing `normalize` method exactly as it is:

```python
class WhoDonConnector:
    source_name = SOURCE_NAME

    def __init__(
        self,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = default_sleep,
    ) -> None:
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
        self._sleep = sleep

    def fetch(self, since: datetime) -> Sequence[RawDocument]:
        retrieved_at = datetime.now(UTC)
        documents: list[RawDocument] = []
        skip = 0

        while True:
            items = self._page(since, skip)
            documents.extend(
                RawDocument(payload=entry, retrieved_at=retrieved_at) for entry in items
            )
            if len(items) < PAGE_SIZE:
                return documents
            skip += PAGE_SIZE

    def _page(self, since: datetime, skip: int) -> list[dict[str, Any]]:
        moment = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        parameters = {
            "$filter": f"PublicationDateAndTime gt {moment}",
            "$orderby": "PublicationDateAndTime asc",
            "$top": str(PAGE_SIZE),
            "$skip": str(skip),
        }
        payload = self._request(parameters)
        value = payload.get("value", [])
        return [entry for entry in value if isinstance(entry, dict)]

    def _request(self, parameters: dict[str, str]) -> dict[str, Any]:
        last_error: Exception | None = None

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._client.get(
                    API_URL, params=parameters, timeout=TIMEOUT_SECONDS
                )
            except (httpx.TimeoutException, httpx.TransportError) as error:
                last_error = error
            else:
                if response.status_code not in RETRY_STATUS:
                    response.raise_for_status()
                    result: dict[str, Any] = response.json()
                    return result
                last_error = httpx.HTTPStatusError(
                    f"WHO API returned {response.status_code}",
                    request=response.request,
                    response=response,
                )

            if attempt < MAX_ATTEMPTS - 1:
                self._sleep(2.0**attempt)

        raise last_error if last_error else httpx.HTTPError("WHO API request failed")
```

Note that `since` is exclusive here: the OData `gt` operator means the newest
already-stored document is not fetched again.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_who_don_fetch.py -v`

Expected: PASS, 6 tests.

- [ ] **Step 6: Run every check**

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/backend/src apps/api/src
```

Expected: all pass. If `ruff format --check` reports a file, run
`uv run ruff format packages database apps/api` and rerun the checks.

- [ ] **Step 7: Commit**

```bash
git add packages/backend uv.lock
git commit -m "feat: fetch WHO outbreak news over HTTP"
```

---

### Task 7: Store signals through a repository

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/repository.py`
- Create: `packages/backend/tests/test_ingestion_repository.py`

- [ ] **Step 1: Write the failing test**

The repository is a thin SQLAlchemy adapter, so the credential-free test proves
it satisfies the Protocol and builds the right `Signal`. Behaviour against a real
database is covered by the live verification in Task 10.

Create `packages/backend/tests/test_ingestion_repository.py`:

```python
from datetime import UTC, datetime
from uuid import uuid4

from episignal_backend.db.types import ProcessingStatus, SignalType
from episignal_backend.ingestion.documents import NormalizedSignal
from episignal_backend.ingestion.protocol import SignalRepository
from episignal_backend.ingestion.repository import SqlAlchemySignalRepository, build_signal

MOMENT = datetime(2026, 8, 14, 15, 38, 29, tzinfo=UTC)
URL = "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615"


def sample() -> NormalizedSignal:
    return NormalizedSignal(
        external_id="2026-DON615",
        url=URL,
        canonical_url=URL,
        title="Ebola disease - Democratic Republic of the Congo",
        raw_text="4665 confirmed cases.",
        published_at=MOMENT,
        retrieved_at=MOMENT,
        content_hash="b" * 64,
    )


def _conforms(repository: SignalRepository) -> SignalRepository:
    # mypy checks this structurally, signatures included. isinstance below only
    # checks that the member NAMES exist, so it cannot stand in for this.
    return repository


def test_sqlalchemy_repository_satisfies_the_protocol() -> None:
    repository = SqlAlchemySignalRepository(session=None)  # type: ignore[arg-type]
    assert isinstance(repository, SignalRepository)
    assert _conforms(repository) is repository


def test_build_signal_maps_every_normalized_field() -> None:
    source_id = uuid4()
    signal = build_signal(sample(), source_id)
    assert signal.source_id == source_id
    assert signal.url == URL
    assert signal.canonical_url == URL
    assert signal.external_id == "2026-DON615"
    assert signal.title == "Ebola disease - Democratic Republic of the Congo"
    assert signal.raw_text == "4665 confirmed cases."
    assert signal.published_at == MOMENT
    assert signal.retrieved_at == MOMENT
    assert signal.language == "en"
    assert signal.content_hash == "b" * 64
    assert signal.signal_type is SignalType.UNKNOWN
    assert signal.processing_status is ProcessingStatus.FETCHED


def test_build_signal_leaves_later_slices_columns_empty() -> None:
    signal = build_signal(sample(), uuid4())
    assert signal.summary is None
    assert signal.relevance_score is None
    assert signal.public_health_relevant is None
    assert signal.ai_extraction is None
    assert signal.ai_model is None
    assert signal.ai_processed_at is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ingestion_repository.py -v`

Expected: FAIL at collection with `ModuleNotFoundError: No module named 'episignal_backend.ingestion.repository'`.

- [ ] **Step 3: Implement the repository**

Create `packages/backend/src/episignal_backend/ingestion/repository.py`:

```python
"""SQLAlchemy implementation of the storage boundary.

Kept deliberately thin: it translates a `NormalizedSignal` into a `Signal` row
and answers existence questions. All ingestion decisions live in `pipeline.py`,
which never imports this module.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from episignal_backend.ingestion.documents import NormalizedSignal
from episignal_backend.models import Signal, Source


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
        language=signal.language,
        content_hash=signal.content_hash,
        signal_type=signal.signal_type,
        processing_status=signal.processing_status,
    )


class SqlAlchemySignalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def source_id(self, name: str) -> UUID | None:
        return self._session.execute(
            select(Source.id).where(Source.name == name)
        ).scalar_one_or_none()

    def latest_published_at(self, source_id: UUID) -> datetime | None:
        return self._session.execute(
            select(func.max(Signal.published_at)).where(Signal.source_id == source_id)
        ).scalar_one_or_none()

    def exists(self, url: str, content_hash: str) -> bool:
        found = self._session.execute(
            select(Signal.id)
            .where(Signal.url == url, Signal.content_hash == content_hash)
            .limit(1)
        ).first()
        return found is not None

    def add(self, signal: NormalizedSignal, source_id: UUID) -> None:
        self._session.add(build_signal(signal, source_id))
        self._session.flush()

    def activate(self, source_id: UUID) -> None:
        self._session.execute(
            update(Source).where(Source.id == source_id).values(active=True)
        )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ingestion_repository.py -v`

Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add packages/backend
git commit -m "feat: add the signal storage boundary"
```

---

### Task 8: Run the ingestion pipeline

**Files:**
- Create: `packages/backend/tests/test_ingestion_pipeline.py`
- Create: `packages/backend/src/episignal_backend/ingestion/pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `packages/backend/tests/test_ingestion_pipeline.py`:

```python
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from episignal_backend.ingestion.documents import NormalizedSignal, RawDocument
from episignal_backend.ingestion.fingerprint import content_hash
from episignal_backend.ingestion.pipeline import (
    DEFAULT_WINDOW_DAYS,
    MissingSourceError,
    run_ingestion,
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
SOURCE = "WHO Disease Outbreak News"
URL = "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615"
TITLE = "Ebola disease - Democratic Republic of the Congo"


def digest(content: str) -> str:
    # Real digests, not synthetic ones: NormalizedSignal requires lowercase hex,
    # and deriving them here keeps the sentinel wording free to be anything.
    return content_hash(TITLE, content)


def signal(content: str = "a") -> NormalizedSignal:
    return NormalizedSignal(
        external_id="2026-DON615",
        url=URL,
        canonical_url=URL,
        title=TITLE,
        raw_text=content,
        published_at=NOW - timedelta(days=1),
        retrieved_at=NOW,
        content_hash=digest(content),
    )


class FakeRepository:
    def __init__(self, source: UUID | None = None) -> None:
        self._source = source if source is not None else uuid4()
        self.stored: list[tuple[str, str]] = []
        self.latest: datetime | None = None
        self.activated = False
        self.commits = 0
        self.rollbacks = 0
        self.missing = False

    def source_id(self, name: str) -> UUID | None:
        return None if self.missing else self._source

    def latest_published_at(self, source_id: UUID) -> datetime | None:
        return self.latest

    def exists(self, url: str, content_hash: str) -> bool:
        return (url, content_hash) in self.stored

    def add(self, item: NormalizedSignal, source_id: UUID) -> None:
        if item.raw_text == "explode":
            raise RuntimeError("cannot store this document")
        self.stored.append((item.url, item.content_hash))

    def activate(self, source_id: UUID) -> None:
        self.activated = True

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeConnector:
    source_name = SOURCE

    def __init__(self, signals: Sequence[NormalizedSignal]) -> None:
        self._signals = signals
        self.since: datetime | None = None

    def fetch(self, since: datetime) -> Sequence[RawDocument]:
        self.since = since
        return [
            RawDocument(payload={"index": index}, retrieved_at=NOW)
            for index in range(len(self._signals))
        ]

    def normalize(self, document: RawDocument) -> NormalizedSignal:
        index = int(document.payload["index"])
        if self._signals[index].raw_text == "unparseable":
            raise ValueError("cannot normalize this document")
        return self._signals[index]


def test_an_unseen_document_is_inserted() -> None:
    repository = FakeRepository()
    result = run_ingestion(repository, FakeConnector([signal()]), now=NOW)
    assert (result.inserted, result.skipped, result.failed) == (1, 0, 0)
    assert repository.stored == [(URL, digest("a"))]


def test_the_same_document_is_skipped_on_a_second_run() -> None:
    repository = FakeRepository()
    run_ingestion(repository, FakeConnector([signal()]), now=NOW)
    result = run_ingestion(repository, FakeConnector([signal()]), now=NOW)
    assert (result.inserted, result.skipped, result.failed) == (0, 1, 0)
    assert len(repository.stored) == 1


def test_a_revised_document_is_stored_as_another_version() -> None:
    repository = FakeRepository()
    run_ingestion(repository, FakeConnector([signal("a")]), now=NOW)
    result = run_ingestion(repository, FakeConnector([signal("b")]), now=NOW)
    assert result.inserted == 1
    assert len(repository.stored) == 2
    assert {url for url, _ in repository.stored} == {URL}


def test_one_unparseable_document_does_not_stop_the_others() -> None:
    repository = FakeRepository()
    connector = FakeConnector([signal("unparseable"), signal("c")])
    result = run_ingestion(repository, connector, now=NOW)
    assert (result.inserted, result.skipped, result.failed) == (1, 0, 1)
    assert repository.stored == [(URL, digest("c"))]


def test_a_storage_failure_rolls_back_only_that_document() -> None:
    repository = FakeRepository()
    connector = FakeConnector([signal("explode"), signal("d")])
    result = run_ingestion(repository, connector, now=NOW)
    assert (result.inserted, result.failed) == (1, 1)
    assert repository.rollbacks == 1


def test_each_stored_document_is_committed_individually() -> None:
    repository = FakeRepository()
    connector = FakeConnector([signal("e"), signal("f")])
    run_ingestion(repository, connector, now=NOW)
    assert repository.commits >= 2


def test_a_missing_source_aborts_before_fetching() -> None:
    repository = FakeRepository()
    repository.missing = True
    connector = FakeConnector([signal()])
    with pytest.raises(MissingSourceError, match=SOURCE):
        run_ingestion(repository, connector, now=NOW)
    assert connector.since is None


def test_a_successful_run_activates_the_source() -> None:
    repository = FakeRepository()
    run_ingestion(repository, FakeConnector([signal()]), now=NOW)
    assert repository.activated is True


def test_the_first_run_uses_the_default_window() -> None:
    connector = FakeConnector([])
    run_ingestion(FakeRepository(), connector, now=NOW)
    assert connector.since == NOW - timedelta(days=DEFAULT_WINDOW_DAYS)


def test_a_later_run_resumes_from_the_newest_stored_document() -> None:
    repository = FakeRepository()
    repository.latest = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    connector = FakeConnector([])
    run_ingestion(repository, connector, now=NOW)
    assert connector.since == repository.latest


def test_an_explicit_since_overrides_the_stored_watermark() -> None:
    repository = FakeRepository()
    repository.latest = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    connector = FakeConnector([])
    requested = datetime(2026, 1, 1, tzinfo=UTC)
    run_ingestion(repository, connector, since=requested, now=NOW)
    assert connector.since == requested
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/backend/tests/test_ingestion_pipeline.py -v`

Expected: FAIL at collection with `ModuleNotFoundError: No module named 'episignal_backend.ingestion.pipeline'`.

- [ ] **Step 3: Implement the pipeline**

Create `packages/backend/src/episignal_backend/ingestion/pipeline.py`:

```python
"""Ingestion decisions.

This module imports neither SQLAlchemy nor httpx. It depends on the two
Protocols in `protocol.py`, which is what makes every decision below testable
with in-memory fakes and no credentials.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from episignal_backend.ingestion.protocol import SignalRepository, SourceConnector

DEFAULT_WINDOW_DAYS = 90

logger = logging.getLogger("episignal_backend.ingestion")


class MissingSourceError(Exception):
    """The connector's source identity has not been seeded."""


@dataclass(frozen=True)
class IngestionResult:
    inserted: int
    skipped: int
    failed: int


def run_ingestion(
    repository: SignalRepository,
    connector: SourceConnector,
    *,
    since: datetime | None = None,
    now: datetime | None = None,
) -> IngestionResult:
    moment = now or datetime.now(UTC)

    source_id = repository.source_id(connector.source_name)
    if source_id is None:
        raise MissingSourceError(connector.source_name)

    window_start = since or repository.latest_published_at(source_id) or (
        moment - timedelta(days=DEFAULT_WINDOW_DAYS)
    )

    inserted = 0
    skipped = 0
    failed = 0

    for document in connector.fetch(window_start):
        try:
            signal = connector.normalize(document)
            if repository.exists(signal.url, signal.content_hash):
                skipped += 1
                continue
            repository.add(signal, source_id)
            repository.commit()
            inserted += 1
        except Exception:
            repository.rollback()
            failed += 1
            logger.exception("Could not ingest a document from %s", connector.source_name)

    repository.activate(source_id)
    repository.commit()

    return IngestionResult(inserted=inserted, skipped=skipped, failed=failed)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_ingestion_pipeline.py -v`

Expected: PASS, 11 tests.

- [ ] **Step 5: Run every check**

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/backend/src apps/api/src
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add packages/backend
git commit -m "feat: run the source ingestion pipeline"
```

---

### Task 9: Wire the command and correct the seed

**Files:**
- Create: `packages/backend/tests/test_ingest_runner.py`
- Create: `packages/backend/src/episignal_backend/ingest_runner.py`
- Modify: `database/seeds/sources.json`
- Modify: `packages/backend/src/episignal_backend/schema_check.py`
- Modify: `packages/backend/tests/test_schema_check.py`
- Modify: `package.json`

- [ ] **Step 1: Write the failing argument-parsing tests**

Create `packages/backend/tests/test_ingest_runner.py`:

```python
from datetime import UTC, datetime

import pytest
from episignal_backend.ingest_runner import parse_arguments


def test_the_connector_name_is_required() -> None:
    with pytest.raises(SystemExit):
        parse_arguments([])


def test_an_unknown_connector_is_rejected() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["ecdc"])


def test_since_defaults_to_none() -> None:
    assert parse_arguments(["who-don"]).since is None


def test_since_is_parsed_as_an_inclusive_utc_date() -> None:
    parsed = parse_arguments(["who-don", "--since", "2026-01-01"])
    assert parsed.since == datetime(2026, 1, 1, tzinfo=UTC)


def test_a_malformed_since_is_rejected() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["who-don", "--since", "last-tuesday"])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest packages/backend/tests/test_ingest_runner.py -v`

Expected: FAIL at collection with `ModuleNotFoundError: No module named 'episignal_backend.ingest_runner'`.

- [ ] **Step 3: Implement the runner**

Create `packages/backend/src/episignal_backend/ingest_runner.py`:

```python
"""Entry point for `pnpm ingest:who`.

Counts only. Failure detail is kept out of stdout because the connection string
and document bodies would otherwise reach the console.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from episignal_backend.db.session import session_scope
from episignal_backend.ingestion.pipeline import MissingSourceError, run_ingestion
from episignal_backend.ingestion.protocol import SourceConnector
from episignal_backend.ingestion.repository import SqlAlchemySignalRepository
from episignal_backend.ingestion.who_don import WhoDonConnector

CONNECTORS = {"who-don": WhoDonConnector}


@dataclass(frozen=True)
class Arguments:
    connector: str
    since: datetime | None


def _utc_date(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--since must be YYYY-MM-DD") from error


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(prog="ingest", description="Ingest source documents.")
    parser.add_argument("connector", choices=sorted(CONNECTORS))
    parser.add_argument(
        "--since",
        type=_utc_date,
        default=None,
        help="Inclusive UTC start date, YYYY-MM-DD. Defaults to the last 90 days.",
    )
    parsed = parser.parse_args(list(argv))
    return Arguments(connector=parsed.connector, since=parsed.since)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    connector: SourceConnector = CONNECTORS[arguments.connector]()

    try:
        with session_scope() as session:
            result = run_ingestion(
                SqlAlchemySignalRepository(session),
                connector,
                since=arguments.since,
            )
    except MissingSourceError:
        print("Source identity is not seeded. Run pnpm db:seed first.", file=sys.stderr)
        return 1
    except Exception:
        print("Ingestion failed before completing. Check the source and the database.", file=sys.stderr)
        return 1

    print(f"inserted={result.inserted} skipped={result.skipped} failed={result.failed}")
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest packages/backend/tests/test_ingest_runner.py -v`

Expected: PASS, 5 tests.

- [ ] **Step 5: Correct the WHO source URL**

In `database/seeds/sources.json`, replace the WHO entry's `feed_url`. The RSS
URL returns HTTP 404; the API endpoint is what the connector actually reads:

```json
    "feed_url": "https://www.who.int/api/news/diseaseoutbreaknews",
```

The full WHO entry then reads:

```json
  {
    "name": "WHO Disease Outbreak News",
    "source_type": "international_organization",
    "country_code": null,
    "base_url": "https://www.who.int/emergencies/disease-outbreak-news",
    "feed_url": "https://www.who.int/api/news/diseaseoutbreaknews",
    "credibility_tier": "official",
    "is_official": true,
    "language": "en",
    "active": false
  },
```

- [ ] **Step 6: Write the failing signal-count test**

Add this to `packages/backend/tests/test_schema_check.py`:

```python
def test_signal_counts_report_zero_for_a_source_with_no_signals() -> None:
    from episignal_backend.schema_check import signal_counts

    assert signal_counts([("WHO Disease Outbreak News", 0)]) == {
        "WHO Disease Outbreak News": 0
    }


def test_signal_counts_preserve_each_source_total() -> None:
    from episignal_backend.schema_check import signal_counts

    assert signal_counts([("WHO Disease Outbreak News", 42), ("ECDC", 0)]) == {
        "WHO Disease Outbreak News": 42,
        "ECDC": 0,
    }
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_schema_check.py -v`

Expected: FAIL with `ImportError: cannot import name 'signal_counts'`.

- [ ] **Step 8: Report signal counts**

In `packages/backend/src/episignal_backend/schema_check.py`, extend the imports:

```python
from collections.abc import Iterable

from sqlalchemy import func, inspect, select

from episignal_backend.models import Disease, Signal, Source
```

Add this function beside `missing_tables`:

```python
def signal_counts(rows: Iterable[tuple[str, int]]) -> dict[str, int]:
    return {name: count for name, count in rows}
```

Inside `build_report`, after the `active_sources` assignment, add:

```python
        signals = signal_counts(
            session.execute(
                select(Source.name, func.count(Signal.id))
                .select_from(Source)
                .outerjoin(Signal, Signal.source_id == Source.id)
                .group_by(Source.name)
            ).all()
        )
```

Add the key to the returned dictionary:

```python
        "signals": signals,
```

- [ ] **Step 9: Run the test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_schema_check.py -v`

Expected: PASS, 4 tests.

- [ ] **Step 10: Add the pnpm script**

In `package.json`, add this line to `scripts`, directly after the `db:seed` entry:

```json
    "ingest:who": "uv run --package episignal-backend python -m episignal_backend.ingest_runner who-don",
```

- [ ] **Step 11: Run every check**

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/backend/src apps/api/src
```

Expected: all pass.

- [ ] **Step 12: Commit**

```bash
git add packages/backend database/seeds/sources.json package.json
git commit -m "feat: add the ingest command and correct the WHO source URL"
```

---

### Task 10: Verify against the live database

This task runs against the real Supabase project named by `apps/api/.env`. It
migrates, seeds and ingests. It creates nothing else and deletes nothing.

**Files:**
- Modify only files that fail a check below.

- [ ] **Step 1: Apply the migration and correct the seed**

```powershell
uv run --package episignal-api alembic -c database/alembic.ini upgrade head
uv run --package episignal-backend python -m episignal_backend.seed_runner
```

Expected: the upgrade exits 0; seeding prints `diseases=29 sources=2`.

- [ ] **Step 2: Confirm the schema changed**

```powershell
uv run --package episignal-backend python -m episignal_backend.schema_check
```

Expected: `postgis` is `up`, `missing_tables` is empty, and `signals` reports
`0` for both sources.

- [ ] **Step 3: Ingest for the first time**

```powershell
uv run --package episignal-backend python -m episignal_backend.ingest_runner who-don
```

Expected: `inserted=N skipped=0 failed=0` with N greater than zero, and exit
code 0. If N is zero, WHO published nothing in the last 90 days; rerun with
`--since 2026-01-01` and expect a non-zero N.

- [ ] **Step 4: Prove the run is idempotent**

```powershell
uv run --package episignal-backend python -m episignal_backend.ingest_runner who-don
uv run --package episignal-backend python -m episignal_backend.schema_check
```

Expected: the second ingestion prints `inserted=0`, and the signal count for
`WHO Disease Outbreak News` is unchanged from Step 3. `active_sources` now
contains `WHO Disease Outbreak News`.

- [ ] **Step 5: Audit what was stored**

```powershell
uv run --package episignal-backend python -c "from sqlalchemy import select; from episignal_backend.db.session import session_scope; from episignal_backend.models import Signal; s=session_scope().__enter__(); rows=s.execute(select(Signal.url, Signal.title, Signal.published_at, Signal.processing_status).limit(5)).all(); [print(r) for r in rows]"
```

Expected: real WHO item URLs, real titles, timezone-aware publication dates, and
`processing_status` of `fetched` on every row. No row has a summary, a relevance
score, or any AI column populated.

- [ ] **Step 6: Run the full verification suite**

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy packages/backend/src apps/api/src
uv run pytest -q
corepack pnpm --filter '@episignal/web' test
corepack pnpm --filter '@episignal/web' lint
corepack pnpm --filter '@episignal/web' typecheck
corepack pnpm --filter '@episignal/web' build
```

Expected: every command exits 0.

- [ ] **Step 7: Audit for leaked secrets**

```powershell
git status --short
git grep -n -I -E 'postgres(ql)?://[^ ]+:[^ ]+@' -- packages database apps scripts package.json
```

Expected: no `.env` file appears in `git status`; the grep returns only the
placeholder in `apps/api/.env.example` and the test and export placeholders.

- [ ] **Step 8: Commit any fixes**

Run `git diff --name-only`, inspect every listed path, and stage each approved
path individually with `git add --` followed by its literal path. Never use
`git add -A`. Commit with:

```bash
git commit -m "fix: complete ingestion verification"
```

Skip this commit when no files changed.

## Primary References

- Design: `docs/superpowers/specs/2026-08-26-who-don-ingestion-design.md`
- Foundation plan: `docs/superpowers/plans/2026-08-26-foundation.md`
- WHO Disease Outbreak News API: https://www.who.int/api/news/diseaseoutbreaknews
- httpx MockTransport: https://www.python-httpx.org/advanced/transports/
- SQLAlchemy 2 ORM queries: https://docs.sqlalchemy.org/en/20/orm/queryguide/select.html
- Alembic constraint operations: https://alembic.sqlalchemy.org/en/latest/ops.html
