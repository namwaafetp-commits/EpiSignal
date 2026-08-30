# AI Classification, Extraction, and Cost Accounting Implementation Plan

**Design:** `docs/superpowers/specs/2026-08-27-ai-extraction-design.md`
**Sub-project:** C of `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md`
**Baseline:** `main` at 357 passing tests, clean `ruff`, clean `mypy`.

Every task is one red-green cycle followed by one commit. Do them in order: each
task's failing test depends only on files that task or an earlier task creates.

## Before you start

Read the design. Then read these four files, which this plan extends rather than
replaces:

- `packages/backend/src/episignal_backend/ingestion/protocol.py` — the Protocol
  style every boundary here follows.
- `packages/backend/src/episignal_backend/ingestion/dedupe.py` — a pure pass over
  a repository, with the same commit-per-item and rollback-on-error shape.
- `packages/backend/src/episignal_backend/ingestion/repository.py` — the storage
  adapter style, and `SqlAlchemyDedupeRepository` in particular.
- `packages/backend/tests/test_dedupe_repository.py` — the `FakeSession` pattern
  every storage test here uses. No test in this plan touches a database.

Six house rules that are not obvious from the code:

1. **Decision modules never import SQLAlchemy or httpx.** In this slice that
   means `schema.py`, `documents.py`, `validate.py`, `ladder.py`, `prompts.py`,
   `classify.py`, and `extract.py`. Only `repository.py` imports SQLAlchemy, and
   only `openrouter.py` imports httpx.
2. **Timestamps are never substituted for one another.** `published_at`,
   `first_seen_at`, `retrieved_at`, `gdelt_seen_at`, `ai_processed_at`,
   `data_as_of`, and `event_date` mean seven different things.
3. **A number is never stored without the span that supports it.** This is the
   rule the whole slice exists to enforce. If a change would let an ungrounded
   number through, the change is wrong.
4. **Absence is `None`, never `False` and never `0`.** A disease the article does
   not name, a count it does not give, and a transmission route it does not
   characterise are all absent.
5. **No test opens a socket or reads a credential.** Model calls go through a
   fake `ChatModel`; the one adapter test uses `httpx.MockTransport`.
6. **The vocabulary in `CONTEXT.md` is the naming authority.** Use tier,
   escalation, source span, grounding, cost row, unavailable, and verdict as they
   are defined there.

Run the full gate after every task:

```bash
uv run pytest
```

---

## File structure

**Create:**

| Path | Responsibility |
| --- | --- |
| `packages/backend/src/episignal_backend/ai/__init__.py` | Package marker. |
| `packages/backend/src/episignal_backend/ai/schema.py` | Pure. The strict extraction and classification schemas. |
| `packages/backend/src/episignal_backend/ai/documents.py` | Pure. Contracts crossing the two seams. |
| `packages/backend/src/episignal_backend/ai/protocol.py` | Pure. `ChatModel` and `AiRepository`. |
| `packages/backend/src/episignal_backend/ai/validate.py` | Pure. Every deterministic check. |
| `packages/backend/src/episignal_backend/ai/ladder.py` | Pure. Tier order, run guards, cost. |
| `packages/backend/src/episignal_backend/ai/prompts.py` | Pure. Prompt construction. |
| `packages/backend/src/episignal_backend/ai/classify.py` | The batched relevance pass. |
| `packages/backend/src/episignal_backend/ai/extract.py` | The per-signal extraction pass. |
| `packages/backend/src/episignal_backend/ai/openrouter.py` | The httpx adapter. |
| `packages/backend/src/episignal_backend/ai/repository.py` | The SQLAlchemy adapter. |
| `packages/backend/src/episignal_backend/models/ai.py` | `AiModel`, `AiRequest`. |
| `packages/backend/src/episignal_backend/extract_runner.py` | CLI for `pnpm extract:signals`. |
| `database/migrations/versions/20260827_0005_ai_extraction.py` | Schema change. |
| `database/seeds/ai_models.json` | The seeded model roster. |
| `packages/backend/tests/test_ai_schema.py` | Schema validation tests. |
| `packages/backend/tests/test_ai_documents.py` | Contract validation tests. |
| `packages/backend/tests/test_ai_protocol.py` | Protocol conformance tests. |
| `packages/backend/tests/test_ai_validate.py` | Every deterministic check. |
| `packages/backend/tests/test_ai_ladder.py` | Tier order, guards, cost. |
| `packages/backend/tests/test_ai_prompts.py` | Prompt construction. |
| `packages/backend/tests/test_ai_classify.py` | Classification pass against fakes. |
| `packages/backend/tests/test_ai_extract.py` | Extraction pass against fakes. |
| `packages/backend/tests/test_openrouter.py` | Adapter against `httpx.MockTransport`. |
| `packages/backend/tests/test_ai_repository.py` | Storage adapter against `FakeSession`. |
| `packages/backend/tests/test_extract_runner.py` | CLI tests. |
| `packages/backend/tests/fixtures/ai_outbreak_body.txt` | English report with counts. |
| `packages/backend/tests/fixtures/ai_multilingual_body.txt` | French report of the same shape. |
| `packages/backend/tests/fixtures/ai_extraction_response.json` | A grounded, acceptable response. |
| `packages/backend/tests/fixtures/ai_ungrounded_response.json` | A response whose span is not in the body. |

**Modify:**

| Path | Change |
| --- | --- |
| `packages/backend/src/episignal_backend/db/types.py` | `+ AiPurpose`, `+ AiOutcome` |
| `packages/backend/src/episignal_backend/models/signal.py` | `+ disease_id` and its index |
| `packages/backend/src/episignal_backend/models/__init__.py` | Export `AiModel` and `AiRequest` |
| `packages/backend/src/episignal_backend/seeds.py` | `+ AiModelSeed`, `+ load_ai_models`, seed them |
| `packages/backend/src/episignal_backend/config.py` | The `openrouter_*` and `ai_*` settings |
| `packages/backend/tests/test_models.py` | The two new models and the new vocabulary |
| `packages/backend/tests/test_seeds.py` | Model roster seeding |
| `packages/backend/tests/test_config.py` | The new settings and their bounds |
| `package.json` | `+ extract:signals` |

---

## Task 1: Vocabulary for request purpose and outcome

**Files:**
- Modify: `packages/backend/src/episignal_backend/db/types.py`
- Test: `packages/backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_models.py`:

```python
def test_ai_purposes_are_stored_as_their_values() -> None:
    from episignal_backend.db.types import AiPurpose

    assert AiPurpose.CLASSIFICATION.value == "classification"
    assert AiPurpose.EXTRACTION.value == "extraction"


def test_ai_outcomes_separate_a_refusal_from_a_bad_answer() -> None:
    from episignal_backend.db.types import AiOutcome

    assert AiOutcome.ACCEPTED.value == "accepted"
    assert AiOutcome.REJECTED.value == "rejected"
    assert AiOutcome.UNAVAILABLE.value == "unavailable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_models.py -k "ai_purposes or ai_outcomes" -v`
Expected: FAIL with `ImportError: cannot import name 'AiPurpose'`

- [ ] **Step 3: Write minimal implementation**

In `packages/backend/src/episignal_backend/db/types.py`, add after `ProcessingStatus`:

```python
class AiPurpose(StrEnum):
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"


class AiOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    # The provider never answered: refused, timed out, or out of quota. Kept
    # apart from REJECTED because nothing was learned about the signal, so the
    # signal must stay selectable rather than be sent for review.
    UNAVAILABLE = "unavailable"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_models.py -k "ai_purposes or ai_outcomes" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/db/types.py packages/backend/tests/test_models.py
git commit -m "feat: add the AI request purpose and outcome vocabulary"
```

---

## Task 2: The strict extraction schema

The schema is the contract with the model and the contract with the database at
once. It is written before anything that produces or consumes it, because every
later task asserts against it.

**Files:**
- Create: `packages/backend/src/episignal_backend/ai/__init__.py`
- Create: `packages/backend/src/episignal_backend/ai/schema.py`
- Test: `packages/backend/tests/test_ai_schema.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_ai_schema.py`:

```python
import pytest
from pydantic import ValidationError

from episignal_backend.ai.schema import Extraction, GroundedCount, GroundedFlag


def minimal(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "signal_type": "outbreak_report",
        "summary": "Health authorities report a cholera outbreak in Luanda province.",
        "disease": {"name": "Cholera", "confidence": 0.97},
        "pathogen": None,
        "locations": [{"role": "primary", "country": "Angola", "place_name": "Luanda"}],
        "epidemiology": {
            "confirmed_cases": {"value": 327, "source_span": "327 confirmed cases"}
        },
        "dates": {"data_as_of": "2026-08-25"},
        "transmission": None,
        "confidence": 0.94,
    }
    payload.update(overrides)
    return payload


def test_a_grounded_extraction_validates() -> None:
    extraction = Extraction.model_validate(minimal())

    assert extraction.disease is not None
    assert extraction.disease.name == "Cholera"
    assert extraction.epidemiology.confirmed_cases == GroundedCount(
        value=327, source_span="327 confirmed cases"
    )
    assert extraction.epidemiology.deaths is None


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(create_or_update_event=True))


def test_a_count_without_a_span_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GroundedCount.model_validate({"value": 327, "source_span": "   "})


def test_a_negative_count_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GroundedCount.model_validate({"value": -1, "source_span": "minus one case"})


def test_a_flag_without_a_span_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GroundedFlag.model_validate({"value": True, "source_span": ""})


def test_an_unknown_signal_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(signal_type="football_match"))


def test_an_unknown_location_role_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(
            minimal(locations=[{"role": "somewhere", "country": "Angola"}])
        )


def test_confidence_outside_zero_to_one_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(confidence=1.4))


def test_a_summary_longer_than_the_bound_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(summary="a" * 401))


def test_the_prompt_schema_names_every_field_the_model_must_return() -> None:
    from episignal_backend.ai.schema import extraction_json_schema

    schema = extraction_json_schema()

    assert schema["additionalProperties"] is False
    assert "epidemiology" in schema["properties"]
    assert "confidence" in schema["properties"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ai_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ai'`

- [ ] **Step 3: Write minimal implementation**

Create an empty `packages/backend/src/episignal_backend/ai/__init__.py`.

Create `packages/backend/src/episignal_backend/ai/schema.py`:

```python
"""The contract with the model, and the shape stored in `signals.ai_extraction`.

Strict on purpose. A model that returns an extra key has not understood the
question, and a key nobody validates is a value nobody can trust. `extra` is
forbidden everywhere, and every number carries the span of the article that
supports it, because a bare number cannot be checked against anything.

This module imports neither SQLAlchemy nor httpx.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from episignal_backend.db.types import LocationRole, SignalType

SUMMARY_MAX_CHARACTERS = 400
SPAN_MAX_CHARACTERS = 300


def _require_span(value: str) -> str:
    collapsed = " ".join(value.split())
    if not collapsed:
        raise ValueError("source_span must quote the article, not be blank")
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
    summary: str = Field(min_length=1, max_length=SUMMARY_MAX_CHARACTERS)
    disease: NamedEntity | None = None
    pathogen: NamedEntity | None = None
    locations: tuple[ExtractedLocation, ...] = ()
    epidemiology: Epidemiology = Epidemiology()
    dates: ExtractedDates = ExtractedDates()
    transmission: Transmission | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("summary")
    @classmethod
    def collapse_summary(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("summary must not be blank")
        return collapsed


def extraction_json_schema() -> dict[str, Any]:
    """The schema the prompt carries, generated from the model it validates.

    One source of truth: a prompt that describes a different shape from the
    validator is a prompt that produces rejections nobody can explain.
    """
    return Extraction.model_json_schema()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ai_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai packages/backend/tests/test_ai_schema.py
git commit -m "feat: add the strict epidemiological extraction schema"
```

---

## Task 3: The classification response schema

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/schema.py`
- Test: `packages/backend/tests/test_ai_schema.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_ai_schema.py`:

```python
def test_a_classification_response_carries_one_verdict_per_signal() -> None:
    from episignal_backend.ai.schema import ClassificationResponse

    response = ClassificationResponse.model_validate(
        {
            "results": [
                {
                    "id": "b3f1c2d4-0000-4000-8000-000000000001",
                    "is_public_health_relevant": True,
                    "signal_type": "outbreak_report",
                    "relevance": 0.88,
                }
            ]
        }
    )

    assert len(response.results) == 1
    assert response.results[0].relevance == 0.88


def test_a_classification_verdict_with_an_unparseable_id_is_rejected() -> None:
    from episignal_backend.ai.schema import ClassificationResponse

    with pytest.raises(ValidationError):
        ClassificationResponse.model_validate(
            {
                "results": [
                    {
                        "id": "the first one",
                        "is_public_health_relevant": True,
                        "signal_type": "outbreak_report",
                        "relevance": 0.88,
                    }
                ]
            }
        )


def test_a_classification_response_with_no_results_is_rejected() -> None:
    from episignal_backend.ai.schema import ClassificationResponse

    with pytest.raises(ValidationError):
        ClassificationResponse.model_validate({"results": []})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ai_schema.py -k classification -v`
Expected: FAIL with `ImportError: cannot import name 'ClassificationResponse'`

- [ ] **Step 3: Write minimal implementation**

Append to `packages/backend/src/episignal_backend/ai/schema.py`:

```python
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
```

Add `from uuid import UUID` to the imports at the top of the same file.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ai_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/schema.py packages/backend/tests/test_ai_schema.py
git commit -m "feat: add the batched classification response schema"
```

---

## Task 4: Contracts crossing the two seams

**Files:**
- Create: `packages/backend/src/episignal_backend/ai/documents.py`
- Test: `packages/backend/tests/test_ai_documents.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_ai_documents.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatRequest,
    ChatResponse,
    ClassifiableSignal,
    ExtractableSignal,
    ModelSpec,
    TokenUsage,
)
from episignal_backend.db.types import AiOutcome, AiPurpose

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


def test_a_model_spec_carries_its_tier_and_its_prices() -> None:
    spec = ModelSpec(
        id=uuid4(),
        tier=1,
        model_id="meta-llama/llama-3.3-70b-instruct:free",
        label="Llama 3.3 70B (free)",
        prompt_price_per_million=Decimal("0"),
        completion_price_per_million=Decimal("0"),
    )

    assert spec.tier == 1
    assert spec.prompt_price_per_million == Decimal("0")


def test_a_tier_outside_the_ladder_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelSpec(
            id=uuid4(),
            tier=0,
            model_id="x",
            label="x",
            prompt_price_per_million=Decimal("0"),
            completion_price_per_million=Decimal("0"),
        )


def test_a_negative_price_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelSpec(
            id=uuid4(),
            tier=1,
            model_id="x",
            label="x",
            prompt_price_per_million=Decimal("-1"),
            completion_price_per_million=Decimal("0"),
        )


def test_a_classifiable_signal_must_carry_text() -> None:
    with pytest.raises(ValidationError):
        ClassifiableSignal(id=uuid4(), title="Measles cases rise", excerpt="   ")


def test_an_extractable_signal_must_carry_text() -> None:
    with pytest.raises(ValidationError):
        ExtractableSignal(id=uuid4(), title="Measles cases rise", raw_text="")


def test_a_chat_response_records_what_the_call_cost_in_tokens_and_time() -> None:
    response = ChatResponse(
        content='{"results": []}',
        usage=TokenUsage(prompt_tokens=1200, completion_tokens=90),
        http_status=200,
        latency_ms=830,
    )

    assert response.usage.prompt_tokens == 1200
    assert response.latency_ms == 830


def test_a_chat_request_names_the_model_it_is_for() -> None:
    request = ChatRequest(
        model_id="meta-llama/llama-3.3-70b-instruct:free",
        system="You extract facts.",
        user="Article text.",
    )

    assert request.model_id.endswith(":free")


def test_a_cost_row_can_describe_a_call_that_never_answered() -> None:
    record = AiRequestRecord(
        ai_model_id=uuid4(),
        model_id="meta-llama/llama-3.3-70b-instruct:free",
        tier=1,
        purpose=AiPurpose.EXTRACTION,
        signal_id=uuid4(),
        batch_size=1,
        prompt_tokens=None,
        completion_tokens=None,
        latency_ms=15000,
        http_status=None,
        outcome=AiOutcome.UNAVAILABLE,
        rejection_reason="timeout",
        prompt_price_per_million=Decimal("0"),
        completion_price_per_million=Decimal("0"),
        cost_usd=Decimal("0"),
        requested_at=NOW,
    )

    assert record.outcome is AiOutcome.UNAVAILABLE
    assert record.prompt_tokens is None


def test_a_cost_row_requires_an_aware_timestamp() -> None:
    with pytest.raises(ValidationError):
        AiRequestRecord(
            ai_model_id=uuid4(),
            model_id="x",
            tier=1,
            purpose=AiPurpose.CLASSIFICATION,
            signal_id=None,
            batch_size=20,
            prompt_tokens=10,
            completion_tokens=10,
            latency_ms=100,
            http_status=200,
            outcome=AiOutcome.ACCEPTED,
            rejection_reason=None,
            prompt_price_per_million=Decimal("0"),
            completion_price_per_million=Decimal("0"),
            cost_usd=Decimal("0"),
            requested_at=datetime(2026, 8, 27, 9, 0),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ai_documents.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ai.documents'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ai/documents.py`:

```python
"""Contracts crossing the model seam and the storage seam.

`ChatRequest` and `ChatResponse` describe one HTTP round trip and know nothing
about price: pricing belongs to the ladder, and a transport that knew prices
would change every time one moved. `AiRequestRecord` is the cost row, and it
carries the price that was in force at the moment of the call, because a price
is a fact about a moment.

This module imports neither SQLAlchemy nor httpx.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from episignal_backend.ai.schema import Extraction
from episignal_backend.db.types import AiOutcome, AiPurpose, SignalType

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


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(min_length=1)
    system: str = Field(min_length=1)
    user: str = Field(min_length=1)


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ai_documents.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/documents.py packages/backend/tests/test_ai_documents.py
git commit -m "feat: add the contracts for the model and storage seams"
```

---

## Task 5: The two boundaries

**Files:**
- Create: `packages/backend/src/episignal_backend/ai/protocol.py`
- Test: `packages/backend/tests/test_ai_protocol.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_ai_protocol.py`:

```python
from collections.abc import Sequence
from uuid import UUID, uuid4

from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatRequest,
    ChatResponse,
    ClassifiableSignal,
    ExtractableSignal,
    ModelSpec,
    StoredExtraction,
    TokenUsage,
    Verdict,
)
from episignal_backend.ai.protocol import AiRepository, ChatModel


class StubModel:
    def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="{}", usage=TokenUsage(), http_status=200, latency_ms=1
        )


class StubRepository:
    def models(self) -> Sequence[ModelSpec]:
        return ()

    def awaiting_classification(self, *, limit: int) -> Sequence[ClassifiableSignal]:
        return ()

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        return ()

    def resolve_disease(self, name: str) -> UUID | None:
        return None

    def record_request(self, record: AiRequestRecord) -> None:
        return None

    def record_classification(self, signal_id: UUID, verdict: Verdict) -> None:
        return None

    def record_extraction(self, signal_id: UUID, stored: StoredExtraction) -> None:
        return None

    def mark_needs_review(self, signal_id: UUID) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_a_chat_model_is_recognised_by_its_single_method() -> None:
    assert isinstance(StubModel(), ChatModel)


def test_a_repository_is_recognised_by_the_whole_storage_boundary() -> None:
    assert isinstance(StubRepository(), AiRepository)


def test_an_object_missing_a_storage_method_is_not_a_repository() -> None:
    class Partial:
        def models(self) -> Sequence[ModelSpec]:
            return ()

    assert not isinstance(Partial(), AiRepository)


def test_the_repository_owns_committing_and_rolling_back() -> None:
    repository = StubRepository()

    assert hasattr(repository, "commit")
    assert hasattr(repository, "rollback")
    assert uuid4() is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ai_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ai.protocol'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ai/protocol.py`:

```python
"""The two boundaries the AI passes depend on.

`classify.py` and `extract.py` import these and nothing else, so every decision
here is testable with in-memory fakes: no database, no network, no credentials.

The repository owns transactions. Nothing above it knows what a session is,
which is why `commit` and `rollback` sit on this Protocol rather than being
reached for through a handle the passes were given.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatRequest,
    ChatResponse,
    ClassifiableSignal,
    ExtractableSignal,
    ModelSpec,
    StoredExtraction,
    Verdict,
)


@runtime_checkable
class ChatModel(Protocol):
    """One request to one model.

    Deliberately one method and no notion of tier: a tier is a model id and a
    price, chosen by the ladder, so one adapter serves the whole ladder.
    """

    def complete(self, request: ChatRequest) -> ChatResponse: ...


@runtime_checkable
class AiRepository(Protocol):
    def models(self) -> Sequence[ModelSpec]: ...

    def awaiting_classification(self, *, limit: int) -> Sequence[ClassifiableSignal]: ...

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]: ...

    def resolve_disease(self, name: str) -> UUID | None: ...

    def record_request(self, record: AiRequestRecord) -> None: ...

    def record_classification(self, signal_id: UUID, verdict: Verdict) -> None: ...

    def record_extraction(self, signal_id: UUID, stored: StoredExtraction) -> None: ...

    def mark_needs_review(self, signal_id: UUID) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class ModelUnavailable(Exception):
    """The provider could not be asked.

    Expected rather than exceptional: free endpoints rate-limit hard and go away
    without notice. Distinct from a rejected answer, because nothing was learned
    about the signal, so the signal must stay exactly as it was.
    """


class NoModelsConfigured(Exception):
    """The roster holds no active row, so there is no ladder to climb."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ai_protocol.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/protocol.py packages/backend/tests/test_ai_protocol.py
git commit -m "feat: add the model and storage boundaries for the AI passes"
```

---
## Task 6: Parsing and structural validation

The first three checks of the design's validation order: the body is JSON, the
JSON fits the schema, and the counts do not contradict each other.

**Files:**
- Create: `packages/backend/src/episignal_backend/ai/validate.py`
- Test: `packages/backend/tests/test_ai_validate.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_ai_validate.py`:

```python
import json

import pytest

from episignal_backend.ai.schema import Extraction
from episignal_backend.ai.validate import RejectionReason, Rejected, parse_extraction

GROUNDED = {
    "signal_type": "outbreak_report",
    "summary": "Cholera outbreak reported in Luanda.",
    "disease": {"name": "Cholera", "confidence": 0.97},
    "epidemiology": {
        "confirmed_cases": {"value": 327, "source_span": "327 confirmed cases"},
        "total_cases": {"value": 400, "source_span": "400 cases in total"},
        "deaths": {"value": 14, "source_span": "14 people have died"},
    },
    "confidence": 0.94,
}


def test_a_well_formed_response_parses_into_an_extraction() -> None:
    extraction = parse_extraction(json.dumps(GROUNDED))

    assert isinstance(extraction, Extraction)
    assert extraction.disease is not None


def test_prose_around_the_json_is_rejected() -> None:
    with pytest.raises(Rejected) as error:
        parse_extraction("Here you go:\n" + json.dumps(GROUNDED))

    assert error.value.reason is RejectionReason.NOT_JSON


def test_a_fenced_code_block_is_rejected() -> None:
    with pytest.raises(Rejected) as error:
        parse_extraction("```json\n" + json.dumps(GROUNDED) + "\n```")

    assert error.value.reason is RejectionReason.NOT_JSON


def test_an_extra_key_is_rejected_as_a_shape_failure() -> None:
    payload = dict(GROUNDED, create_or_update_event=True)

    with pytest.raises(Rejected) as error:
        parse_extraction(json.dumps(payload))

    assert error.value.reason is RejectionReason.SHAPE


def test_deaths_above_total_cases_are_rejected() -> None:
    payload = json.loads(json.dumps(GROUNDED))
    payload["epidemiology"]["deaths"] = {"value": 900, "source_span": "900 died"}

    with pytest.raises(Rejected) as error:
        parse_extraction(json.dumps(payload))

    assert error.value.reason is RejectionReason.ARITHMETIC


def test_confirmed_and_suspected_above_total_are_rejected() -> None:
    payload = json.loads(json.dumps(GROUNDED))
    payload["epidemiology"]["suspected_cases"] = {
        "value": 200,
        "source_span": "200 suspected cases",
    }

    with pytest.raises(Rejected) as error:
        parse_extraction(json.dumps(payload))

    assert error.value.reason is RejectionReason.ARITHMETIC


def test_new_deaths_above_deaths_are_rejected() -> None:
    payload = json.loads(json.dumps(GROUNDED))
    payload["epidemiology"]["new_deaths"] = {"value": 20, "source_span": "20 new deaths"}

    with pytest.raises(Rejected) as error:
        parse_extraction(json.dumps(payload))

    assert error.value.reason is RejectionReason.ARITHMETIC


def test_a_comparison_with_a_missing_side_is_not_a_contradiction() -> None:
    payload = json.loads(json.dumps(GROUNDED))
    del payload["epidemiology"]["total_cases"]

    extraction = parse_extraction(json.dumps(payload))

    assert extraction.epidemiology.total_cases is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ai_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ai.validate'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ai/validate.py`:

```python
"""Every deterministic check a model answer must pass before it is stored.

The order matters and is the design's order: parse, shape, batch identity,
arithmetic, grounding, emptiness, privacy, confidence. Confidence is last on
purpose, so that a confident fabrication is caught by grounding long before the
model's opinion of itself is consulted.

This module imports neither SQLAlchemy nor httpx.
"""

import json
from enum import StrEnum

from pydantic import ValidationError

from episignal_backend.ai.schema import Epidemiology, Extraction, GroundedCount


class RejectionReason(StrEnum):
    NOT_JSON = "not_json"
    SHAPE = "shape"
    BATCH_IDENTITY = "batch_identity"
    ARITHMETIC = "arithmetic"
    UNGROUNDED = "ungrounded"
    EMPTY_CLAIM = "empty_claim"
    PRIVACY = "privacy"
    LOW_CONFIDENCE = "low_confidence"


class Rejected(Exception):
    """The answer arrived and cannot be trusted.

    Carries the name of the first check that failed, which is what the cost row
    records and what the admin view will show.
    """

    def __init__(self, reason: RejectionReason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


def _loads(content: str) -> object:
    # No salvaging: a model that wrapped its answer in prose or a code fence did
    # not follow the contract, and stripping the wrapper teaches it that the
    # contract is optional. Escalating is cheaper than a parser that guesses.
    try:
        return json.loads(content)
    except json.JSONDecodeError as error:
        raise Rejected(RejectionReason.NOT_JSON, str(error)) from error


def _at_most(smaller: GroundedCount | None, larger: GroundedCount | None, label: str) -> None:
    if smaller is None or larger is None:
        return
    if smaller.value > larger.value:
        raise Rejected(RejectionReason.ARITHMETIC, label)


def check_arithmetic(epidemiology: Epidemiology) -> None:
    total = epidemiology.total_cases
    _at_most(epidemiology.deaths, total, "deaths above total_cases")
    _at_most(epidemiology.new_cases, total, "new_cases above total_cases")
    _at_most(epidemiology.confirmed_cases, total, "confirmed_cases above total_cases")
    _at_most(epidemiology.suspected_cases, total, "suspected_cases above total_cases")
    _at_most(epidemiology.new_deaths, epidemiology.deaths, "new_deaths above deaths")

    confirmed = epidemiology.confirmed_cases
    suspected = epidemiology.suspected_cases
    if total is not None and confirmed is not None and suspected is not None:
        if confirmed.value + suspected.value > total.value:
            raise Rejected(
                RejectionReason.ARITHMETIC, "confirmed_cases plus suspected_cases above total_cases"
            )


def parse_extraction(content: str) -> Extraction:
    payload = _loads(content)
    try:
        extraction = Extraction.model_validate(payload)
    except ValidationError as error:
        raise Rejected(RejectionReason.SHAPE, error.title) from error

    check_arithmetic(extraction.epidemiology)
    return extraction
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ai_validate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/validate.py packages/backend/tests/test_ai_validate.py
git commit -m "feat: parse and structurally validate an extraction response"
```

---

## Task 7: Grounding, emptiness, privacy, and confidence

The check the whole sub-project exists for. An extracted number is accepted only
if the article contains the words that state it.

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/validate.py`
- Create: `packages/backend/tests/fixtures/ai_outbreak_body.txt`
- Create: `packages/backend/tests/fixtures/ai_ungrounded_response.json`
- Test: `packages/backend/tests/test_ai_validate.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/fixtures/ai_outbreak_body.txt`:

```text
LUANDA — Angola's health ministry said on Monday that a cholera outbreak in
Luanda province has grown, with 327 confirmed cases recorded since the start of
August and 400 cases in total once suspected infections are included.

Officials said 14 people have died. The ministry said all cases were acquired
locally and that no imported infection had been identified. Figures are current
as of 25 August 2026.

Treatment centres in the Cazenga and Viana districts are operating above
capacity, and the ministry has asked partners for oral rehydration supplies.
```

Create `packages/backend/tests/fixtures/ai_ungrounded_response.json`:

```json
{
  "signal_type": "outbreak_report",
  "summary": "Cholera outbreak reported in Luanda province.",
  "disease": { "name": "Cholera", "confidence": 0.97 },
  "locations": [{ "role": "primary", "country": "Angola", "place_name": "Luanda" }],
  "epidemiology": {
    "confirmed_cases": { "value": 327, "source_span": "327 confirmed cases" },
    "deaths": { "value": 51, "source_span": "51 people have died" }
  },
  "dates": { "data_as_of": "2026-08-25" },
  "confidence": 0.96
}
```

Append to `packages/backend/tests/test_ai_validate.py`:

```python
from pathlib import Path

from episignal_backend.ai.validate import MIN_CONFIDENCE_DEFAULT, validate_extraction

FIXTURES = Path(__file__).parent / "fixtures"
BODY = (FIXTURES / "ai_outbreak_body.txt").read_text(encoding="utf-8")


def grounded_payload() -> dict[str, object]:
    return {
        "signal_type": "outbreak_report",
        "summary": "Cholera outbreak reported in Luanda province.",
        "disease": {"name": "Cholera", "confidence": 0.97},
        "locations": [{"role": "primary", "country": "Angola", "place_name": "Luanda"}],
        "epidemiology": {
            "confirmed_cases": {"value": 327, "source_span": "327 confirmed cases"},
            "total_cases": {"value": 400, "source_span": "400 cases in total"},
            "deaths": {"value": 14, "source_span": "14 people have died"},
        },
        "dates": {"data_as_of": "2026-08-25"},
        "transmission": {
            "local_transmission": {
                "value": True,
                "source_span": "all cases were acquired locally",
            }
        },
        "confidence": 0.94,
    }


def test_an_extraction_whose_spans_are_in_the_article_is_accepted() -> None:
    extraction = validate_extraction(json.dumps(grounded_payload()), BODY)

    assert extraction.epidemiology.deaths is not None
    assert extraction.epidemiology.deaths.value == 14


def test_a_span_the_article_does_not_contain_is_rejected() -> None:
    content = (FIXTURES / "ai_ungrounded_response.json").read_text(encoding="utf-8")

    with pytest.raises(Rejected) as error:
        validate_extraction(content, BODY)

    assert error.value.reason is RejectionReason.UNGROUNDED


def test_a_span_that_does_not_contain_its_own_number_is_rejected() -> None:
    payload = grounded_payload()
    payload["epidemiology"] = {
        "deaths": {"value": 14, "source_span": "Officials said"}
    }

    with pytest.raises(Rejected) as error:
        validate_extraction(json.dumps(payload), BODY)

    assert error.value.reason is RejectionReason.UNGROUNDED


def test_a_span_is_matched_across_a_line_break_in_the_article() -> None:
    payload = grounded_payload()
    payload["epidemiology"] = {
        "confirmed_cases": {"value": 327, "source_span": "327 confirmed cases recorded"}
    }

    extraction = validate_extraction(json.dumps(payload), BODY)

    assert extraction.epidemiology.confirmed_cases is not None


def test_a_transmission_object_with_no_flags_is_stored_as_absent() -> None:
    payload = grounded_payload()
    payload["transmission"] = {}

    extraction = validate_extraction(json.dumps(payload), BODY)

    assert extraction.transmission is None


def test_an_ungrounded_transmission_flag_is_rejected() -> None:
    payload = grounded_payload()
    payload["transmission"] = {
        "imported": {"value": True, "source_span": "the case was imported from Namibia"}
    }

    with pytest.raises(Rejected) as error:
        validate_extraction(json.dumps(payload), BODY)

    assert error.value.reason is RejectionReason.UNGROUNDED


def test_a_summary_carrying_a_telephone_number_is_rejected() -> None:
    payload = grounded_payload()
    payload["summary"] = "Call the family on +244 923 555 0142 for details."

    with pytest.raises(Rejected) as error:
        validate_extraction(json.dumps(payload), BODY)

    assert error.value.reason is RejectionReason.PRIVACY


def test_a_place_name_carrying_an_email_address_is_rejected() -> None:
    payload = grounded_payload()
    payload["locations"] = [
        {"role": "primary", "country": "Angola", "place_name": "contact@example.com"}
    ]

    with pytest.raises(Rejected) as error:
        validate_extraction(json.dumps(payload), BODY)

    assert error.value.reason is RejectionReason.PRIVACY


def test_confidence_below_the_floor_is_rejected() -> None:
    payload = grounded_payload()
    payload["confidence"] = 0.2

    with pytest.raises(Rejected) as error:
        validate_extraction(json.dumps(payload), BODY, min_confidence=MIN_CONFIDENCE_DEFAULT)

    assert error.value.reason is RejectionReason.LOW_CONFIDENCE


def test_grounding_is_checked_before_confidence() -> None:
    payload = grounded_payload()
    payload["confidence"] = 0.1
    payload["epidemiology"] = {"deaths": {"value": 99, "source_span": "99 people have died"}}

    with pytest.raises(Rejected) as error:
        validate_extraction(json.dumps(payload), BODY)

    assert error.value.reason is RejectionReason.UNGROUNDED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ai_validate.py -k "grounded or span or transmission or privacy or confidence" -v`
Expected: FAIL with `ImportError: cannot import name 'validate_extraction'`

- [ ] **Step 3: Write minimal implementation**

Append to `packages/backend/src/episignal_backend/ai/validate.py`:

```python
MIN_CONFIDENCE_DEFAULT = 0.60

# Deliberately narrow. This is a check on what this system agrees to store, not
# a PII detector and not a claim about what the publisher wrote. A false
# positive costs one escalation; a false negative stores a person's contact
# details in an evidence column.
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_TELEPHONE = re.compile(r"(?:\+\d[\d\s().-]{7,}\d)|(?:\b\d[\d\s().-]{8,}\d\b)")
_LONG_DIGIT_RUN = re.compile(r"\d{9,}")


def _flatten(text: str) -> str:
    """Whitespace-collapsed and case-folded, so a reflowed article still matches.

    A span copied out of a page that wraps mid-sentence differs from the stored
    text only in whitespace, and rejecting that would reject the honest case.
    """
    return " ".join(text.split()).casefold()


def check_privacy(extraction: Extraction) -> None:
    candidates = [extraction.summary]
    candidates.extend(
        location.place_name for location in extraction.locations if location.place_name
    )
    for candidate in candidates:
        for pattern in (_EMAIL, _TELEPHONE, _LONG_DIGIT_RUN):
            if pattern.search(candidate):
                raise Rejected(RejectionReason.PRIVACY, pattern.pattern)


def _check_span(span: str, flat_body: str, label: str) -> None:
    if _flatten(span) not in flat_body:
        raise Rejected(RejectionReason.UNGROUNDED, label)


def check_grounding(extraction: Extraction, raw_text: str) -> None:
    flat_body = _flatten(raw_text)

    for label, count in (
        ("suspected_cases", extraction.epidemiology.suspected_cases),
        ("confirmed_cases", extraction.epidemiology.confirmed_cases),
        ("total_cases", extraction.epidemiology.total_cases),
        ("deaths", extraction.epidemiology.deaths),
        ("new_cases", extraction.epidemiology.new_cases),
        ("new_deaths", extraction.epidemiology.new_deaths),
    ):
        if count is None:
            continue
        _check_span(count.source_span, flat_body, label)
        # The span must state this number, not merely sit near it. Without this,
        # any true sentence in the article would support any number at all.
        if str(count.value) not in count.source_span:
            raise Rejected(RejectionReason.UNGROUNDED, f"{label} not stated by its span")

    if extraction.transmission is not None:
        for label, flag in (
            ("local_transmission", extraction.transmission.local_transmission),
            ("imported", extraction.transmission.imported),
        ):
            if flag is not None:
                _check_span(flag.source_span, flat_body, label)


def validate_extraction(
    content: str, raw_text: str, *, min_confidence: float = MIN_CONFIDENCE_DEFAULT
) -> Extraction:
    """Every check, in the design's order. The first failure raises."""
    extraction = parse_extraction(content)

    check_grounding(extraction, raw_text)

    if extraction.transmission is not None and extraction.transmission.is_empty():
        # An object with no flags is not a finding. Stored as absence rather
        # than rejected, because saying nothing about transmission is a normal
        # thing for an article to do.
        extraction = extraction.model_copy(update={"transmission": None})

    check_privacy(extraction)

    if extraction.confidence < min_confidence:
        raise Rejected(RejectionReason.LOW_CONFIDENCE, f"{extraction.confidence}")

    return extraction
```

Add `import re` to the imports at the top of the same file.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ai_validate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/validate.py packages/backend/tests/test_ai_validate.py packages/backend/tests/fixtures/ai_outbreak_body.txt packages/backend/tests/fixtures/ai_ungrounded_response.json
git commit -m "feat: reject extractions the article does not support"
```

---

## Task 8: Batch identity

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/validate.py`
- Test: `packages/backend/tests/test_ai_validate.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_ai_validate.py`:

```python
from uuid import UUID, uuid4

from episignal_backend.ai.validate import validate_classification

FIRST = UUID("b3f1c2d4-0000-4000-8000-000000000001")
SECOND = UUID("b3f1c2d4-0000-4000-8000-000000000002")


def verdict(identifier: UUID, relevant: bool = True) -> dict[str, object]:
    return {
        "id": str(identifier),
        "is_public_health_relevant": relevant,
        "signal_type": "outbreak_report" if relevant else "unknown",
        "relevance": 0.88 if relevant else 0.04,
    }


def test_a_response_covering_exactly_the_batch_is_accepted() -> None:
    content = json.dumps({"results": [verdict(FIRST), verdict(SECOND, relevant=False)]})

    response = validate_classification(content, (FIRST, SECOND))

    assert {result.id for result in response.results} == {FIRST, SECOND}


def test_an_id_that_was_never_sent_rejects_the_whole_response() -> None:
    content = json.dumps({"results": [verdict(FIRST), verdict(uuid4())]})

    with pytest.raises(Rejected) as error:
        validate_classification(content, (FIRST, SECOND))

    assert error.value.reason is RejectionReason.BATCH_IDENTITY


def test_a_missing_id_rejects_the_whole_response() -> None:
    content = json.dumps({"results": [verdict(FIRST)]})

    with pytest.raises(Rejected) as error:
        validate_classification(content, (FIRST, SECOND))

    assert error.value.reason is RejectionReason.BATCH_IDENTITY


def test_a_repeated_id_rejects_the_whole_response() -> None:
    content = json.dumps({"results": [verdict(FIRST), verdict(FIRST)]})

    with pytest.raises(Rejected) as error:
        validate_classification(content, (FIRST, SECOND))

    assert error.value.reason is RejectionReason.BATCH_IDENTITY


def test_a_malformed_classification_body_is_rejected_before_identity() -> None:
    with pytest.raises(Rejected) as error:
        validate_classification("not json at all", (FIRST,))

    assert error.value.reason is RejectionReason.NOT_JSON
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ai_validate.py -k "batch or response_covering or repeated_id or missing_id" -v`
Expected: FAIL with `ImportError: cannot import name 'validate_classification'`

- [ ] **Step 3: Write minimal implementation**

Append to `packages/backend/src/episignal_backend/ai/validate.py`:

```python
def validate_classification(
    content: str, sent: Sequence[UUID]
) -> ClassificationResponse:
    """Accept a batch answer only if it answers exactly the batch that was sent.

    Whole-response rejection is deliberate. A model that returns an id nobody
    sent has lost track of which document it is describing, and there is no
    reason to believe the entries that happen to carry the right ids describe
    the right documents either.
    """
    payload = _loads(content)
    try:
        response = ClassificationResponse.model_validate(payload)
    except ValidationError as error:
        raise Rejected(RejectionReason.SHAPE, error.title) from error

    returned = [result.id for result in response.results]
    if len(returned) != len(set(returned)):
        raise Rejected(RejectionReason.BATCH_IDENTITY, "repeated id")
    if set(returned) != set(sent):
        raise Rejected(RejectionReason.BATCH_IDENTITY, "id set does not match the batch")

    return response
```

Add to the imports at the top of the same file:

```python
from collections.abc import Sequence
from uuid import UUID

from episignal_backend.ai.schema import ClassificationResponse
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ai_validate.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/validate.py packages/backend/tests/test_ai_validate.py
git commit -m "feat: reject a batch answer that does not match the batch sent"
```

---

## Task 9: The ladder, its guards, and cost

**Files:**
- Create: `packages/backend/src/episignal_backend/ai/ladder.py`
- Test: `packages/backend/tests/test_ai_ladder.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_ai_ladder.py`:

```python
from decimal import Decimal
from uuid import uuid4

import pytest

from episignal_backend.ai.documents import ModelSpec, TokenUsage
from episignal_backend.ai.ladder import Guards, Ladder, RunBudget, cost_usd
from episignal_backend.ai.protocol import NoModelsConfigured


def spec(tier: int, prompt: str = "0", completion: str = "0") -> ModelSpec:
    return ModelSpec(
        id=uuid4(),
        tier=tier,
        model_id=f"vendor/model-tier-{tier}:free",
        label=f"Tier {tier}",
        prompt_price_per_million=Decimal(prompt),
        completion_price_per_million=Decimal(completion),
    )


def test_the_ladder_starts_at_the_lowest_tier() -> None:
    ladder = Ladder.build((spec(3), spec(1), spec(2)), max_tier=3)

    assert [rung.tier for rung in ladder.rungs] == [1, 2, 3]


def test_the_ladder_stops_at_the_configured_maximum() -> None:
    ladder = Ladder.build((spec(1), spec(2), spec(3)), max_tier=2)

    assert [rung.tier for rung in ladder.rungs] == [1, 2]


def test_a_ladder_with_no_rungs_is_refused() -> None:
    with pytest.raises(NoModelsConfigured):
        Ladder.build((), max_tier=3)


def test_two_rows_on_the_same_tier_both_stay_on_the_ladder() -> None:
    ladder = Ladder.build((spec(1), spec(1), spec(2)), max_tier=3)

    assert len(ladder.rungs) == 3


def test_a_free_call_costs_nothing_but_is_still_priced() -> None:
    assert cost_usd(TokenUsage(prompt_tokens=1000, completion_tokens=500), spec(1)) == Decimal("0")


def test_a_priced_call_is_computed_per_million_tokens() -> None:
    priced = spec(2, prompt="0.100000", completion="0.400000")

    amount = cost_usd(TokenUsage(prompt_tokens=1_000_000, completion_tokens=500_000), priced)

    assert amount == Decimal("0.300000")


def test_missing_token_counts_cost_nothing_rather_than_guessing() -> None:
    assert cost_usd(TokenUsage(), spec(2, prompt="1", completion="1")) == Decimal("0")


def test_the_request_guard_stops_a_run_before_the_next_call() -> None:
    budget = RunBudget(Guards(max_requests=2, max_cost_usd=Decimal("1")))

    budget.record(Decimal("0"))
    budget.record(Decimal("0"))

    assert budget.exhausted is True


def test_the_cost_guard_stops_a_run_before_the_next_call() -> None:
    budget = RunBudget(Guards(max_requests=100, max_cost_usd=Decimal("0.10")))

    budget.record(Decimal("0.09"))
    assert budget.exhausted is False

    budget.record(Decimal("0.02"))
    assert budget.exhausted is True


def test_a_fresh_budget_is_not_exhausted() -> None:
    assert RunBudget(Guards(max_requests=1, max_cost_usd=Decimal("1"))).exhausted is False


def test_the_budget_reports_what_it_spent() -> None:
    budget = RunBudget(Guards(max_requests=10, max_cost_usd=Decimal("1")))

    budget.record(Decimal("0.02"))
    budget.record(Decimal("0.03"))

    assert budget.requests == 2
    assert budget.spent == Decimal("0.05")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ai_ladder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ai.ladder'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ai/ladder.py`:

```python
"""Which model to ask next, whether the run may ask at all, and what it cost.

Pure arithmetic and ordering. Nothing here performs a request; the passes do
that, and hand the outcome back so the budget stays the single place that knows
how much of the run remains.

This module imports neither SQLAlchemy nor httpx.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from episignal_backend.ai.documents import ModelSpec, TokenUsage
from episignal_backend.ai.protocol import NoModelsConfigured

PER_MILLION = Decimal(1_000_000)
COST_PLACES = Decimal("0.000001")


def cost_usd(usage: TokenUsage, spec: ModelSpec) -> Decimal:
    """Computed from the roster's prices, never from what the provider reports.

    A provider-reported cost is a number we cannot reproduce and cannot audit. A
    missing token count contributes nothing rather than an estimate, because an
    invented number in a ledger is worse than a gap in one.
    """
    prompt = Decimal(usage.prompt_tokens or 0) * spec.prompt_price_per_million
    completion = Decimal(usage.completion_tokens or 0) * spec.completion_price_per_million
    return ((prompt + completion) / PER_MILLION).quantize(COST_PLACES)


@dataclass(frozen=True)
class Guards:
    """What stops a run. Requests bind first under a free ladder; cost binds
    first once a paid rung exists."""

    max_requests: int
    max_cost_usd: Decimal


@dataclass
class RunBudget:
    guards: Guards
    requests: int = 0
    spent: Decimal = field(default=Decimal("0"))

    def record(self, amount: Decimal) -> None:
        self.requests += 1
        self.spent += amount

    @property
    def exhausted(self) -> bool:
        return self.requests >= self.guards.max_requests or self.spent >= self.guards.max_cost_usd


@dataclass(frozen=True)
class Ladder:
    """The rungs, lowest tier first."""

    rungs: tuple[ModelSpec, ...]

    @classmethod
    def build(cls, specs: Sequence[ModelSpec], *, max_tier: int) -> "Ladder":
        # Sorted by tier then model id: a stable order matters because two rows
        # may share a tier, and a run that climbs in a different order each time
        # cannot be compared with the previous one.
        rungs = tuple(
            sorted(
                (spec for spec in specs if spec.tier <= max_tier),
                key=lambda spec: (spec.tier, spec.model_id),
            )
        )
        if not rungs:
            raise NoModelsConfigured("no active model at or below the configured maximum tier")
        return cls(rungs=rungs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ai_ladder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/ladder.py packages/backend/tests/test_ai_ladder.py
git commit -m "feat: add the model ladder, its run guards, and cost computation"
```

---

## Task 10: Prompts

**Files:**
- Create: `packages/backend/src/episignal_backend/ai/prompts.py`
- Test: `packages/backend/tests/test_ai_prompts.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_ai_prompts.py`:

```python
import json
from uuid import UUID

from episignal_backend.ai.documents import ClassifiableSignal, ExtractableSignal
from episignal_backend.ai.prompts import (
    classification_prompt,
    extraction_prompt,
    truncate,
)

FIRST = UUID("b3f1c2d4-0000-4000-8000-000000000001")


def test_truncation_stops_at_a_whitespace_boundary() -> None:
    assert truncate("one two three four", 11) == "one two"


def test_text_shorter_than_the_limit_is_untouched() -> None:
    assert truncate("one two", 100) == "one two"


def test_truncation_of_text_with_no_whitespace_still_bounds_the_length() -> None:
    assert len(truncate("a" * 50, 10)) == 10


def test_an_extraction_prompt_carries_the_schema_and_the_article() -> None:
    signal = ExtractableSignal(
        id=FIRST, title="Cholera cases rise", raw_text="327 confirmed cases were recorded."
    )

    system, user = extraction_prompt(signal, max_characters=1000)

    assert "source_span" in system
    assert "327 confirmed cases were recorded." in user
    assert "Cholera cases rise" in user


def test_an_extraction_prompt_forbids_inventing_a_number() -> None:
    signal = ExtractableSignal(id=FIRST, title="t", raw_text="body")

    system, _ = extraction_prompt(signal, max_characters=1000)

    assert "null" in system


def test_an_extraction_prompt_truncates_a_long_article() -> None:
    signal = ExtractableSignal(id=FIRST, title="t", raw_text="word " * 500)

    _, user = extraction_prompt(signal, max_characters=100)

    assert len(user) < 400


def test_a_classification_prompt_addresses_every_signal_by_id() -> None:
    batch = (
        ClassifiableSignal(id=FIRST, title="Cholera cases rise", excerpt="Health officials said"),
    )

    _, user = classification_prompt(batch, max_characters=1000)

    assert str(FIRST) in user
    assert "Cholera cases rise" in user


def test_a_classification_prompt_divides_the_budget_across_the_batch() -> None:
    batch = tuple(
        ClassifiableSignal(id=FIRST, title=f"Title {index}", excerpt="word " * 200)
        for index in range(4)
    )

    _, user = classification_prompt(batch, max_characters=400)

    assert len(user) < 1200


def test_the_extraction_system_prompt_contains_the_generated_schema() -> None:
    signal = ExtractableSignal(id=FIRST, title="t", raw_text="body")

    system, _ = extraction_prompt(signal, max_characters=100)

    assert json.loads(system[system.index("{") :])["additionalProperties"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ai_prompts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ai.prompts'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ai/prompts.py`:

```python
"""Prompt construction, generated from the schemas that validate the answers.

Written as data, not as f-strings scattered through the passes, so that the
benchmarking harness in sub-project F can compare models against a prompt that
is known to be identical between runs.

This module imports neither SQLAlchemy nor httpx.
"""

import json
from collections.abc import Sequence

from episignal_backend.ai.documents import ClassifiableSignal, ExtractableSignal
from episignal_backend.ai.schema import classification_json_schema, extraction_json_schema

EXTRACTION_RULES = """You read one news article and return epidemiological facts as JSON.

Rules:
- Return one JSON object and nothing else. No prose, no code fence.
- Every count and every transmission flag must include source_span: a short
  phrase copied word for word from the article that states it.
- If the article does not state something, return null. Never infer, never
  estimate, never carry a number over from general knowledge.
- Do not state that an outbreak is confirmed. Report what the article reports.
- Do not include any person's name, telephone number, or address.

The object must match this JSON Schema exactly:
"""

CLASSIFICATION_RULES = """You decide whether each news item concerns a public health event.

Rules:
- Return one JSON object and nothing else. No prose, no code fence.
- Return exactly one result for every id you are given, and no other id.
- Copy each id back character for character.
- When you are unsure, mark it relevant: a missed outbreak costs more than a
  wasted extraction.

The object must match this JSON Schema exactly:
"""


def truncate(text: str, limit: int) -> str:
    """Cut at a whitespace boundary so a word is never split mid-token.

    Falls back to a hard cut when there is no whitespace to cut at, because a
    bound that can be exceeded is not a bound.
    """
    if len(text) <= limit:
        return text
    window = text[:limit]
    boundary = window.rfind(" ")
    return window[:boundary] if boundary > 0 else window


def extraction_prompt(signal: ExtractableSignal, *, max_characters: int) -> tuple[str, str]:
    system = EXTRACTION_RULES + json.dumps(extraction_json_schema(), sort_keys=True)
    user = f"TITLE: {signal.title}\n\nARTICLE:\n{truncate(signal.raw_text, max_characters)}"
    return system, user


def classification_prompt(
    batch: Sequence[ClassifiableSignal], *, max_characters: int
) -> tuple[str, str]:
    system = CLASSIFICATION_RULES + json.dumps(classification_json_schema(), sort_keys=True)
    # The budget is divided rather than applied per item, so a batch of twenty
    # costs the same input as a batch of four and the run's cost stays
    # predictable from the settings alone.
    share = max(1, max_characters // max(1, len(batch)))
    items = "\n\n".join(
        f"id: {signal.id}\ntitle: {signal.title}\nexcerpt: {truncate(signal.excerpt, share)}"
        for signal in batch
    )
    return system, items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ai_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/prompts.py packages/backend/tests/test_ai_prompts.py
git commit -m "feat: build prompts from the schemas that validate the answers"
```

---
## Task 11: The roster and ledger models, and the disease link

**Files:**
- Create: `packages/backend/src/episignal_backend/models/ai.py`
- Modify: `packages/backend/src/episignal_backend/models/signal.py`
- Modify: `packages/backend/src/episignal_backend/models/__init__.py`
- Test: `packages/backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_models.py`:

```python
def test_the_model_roster_orders_the_ladder_by_tier() -> None:
    from episignal_backend.models import AiModel

    assert AiModel.__tablename__ == "ai_models"
    assert {"tier", "model_id", "prompt_price_per_million"} <= set(
        AiModel.__table__.columns.keys()
    )
    assert AiModel.__table__.columns["model_id"].unique is True


def test_a_cost_row_keeps_the_price_that_was_charged() -> None:
    from episignal_backend.models import AiRequest

    columns = set(AiRequest.__table__.columns.keys())

    assert {
        "model_id",
        "tier",
        "purpose",
        "signal_id",
        "batch_size",
        "prompt_tokens",
        "completion_tokens",
        "latency_ms",
        "http_status",
        "outcome",
        "rejection_reason",
        "prompt_price_per_million",
        "completion_price_per_million",
        "cost_usd",
        "requested_at",
    } <= columns


def test_retiring_a_model_does_not_delete_its_spend() -> None:
    from episignal_backend.models import AiRequest

    foreign_key = next(
        key
        for key in AiRequest.__table__.foreign_keys
        if key.column.table.name == "ai_models"
    )

    assert foreign_key.ondelete == "SET NULL"


def test_a_signal_links_to_the_disease_it_resolved_to() -> None:
    from episignal_backend.models import Signal

    assert "disease_id" in Signal.__table__.columns
    assert Signal.__table__.columns["disease_id"].nullable is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_models.py -k "roster or cost_row or retiring or resolved_to" -v`
Expected: FAIL with `ImportError: cannot import name 'AiModel' from 'episignal_backend.models'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/models/ai.py`:

```python
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin, TimestampMixin
from episignal_backend.db.types import AiOutcome, AiPurpose, vocabulary

PRICE = Numeric(12, 6)


class AiModel(IdentityMixin, TimestampMixin, Base):
    """One rung of the escalation ladder.

    A row, not a constant: a free endpoint can be withdrawn without notice, and
    replacing it must not require a deployment.
    """

    __tablename__ = "ai_models"
    __table_args__ = (
        UniqueConstraint("model_id", name="uq_ai_models_model_id"),
        CheckConstraint("tier >= 1 AND tier <= 3", name="tier_range"),
        Index("ix_ai_models_tier", "tier"),
    )

    tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_price_per_million: Mapped[Decimal] = mapped_column(
        PRICE, nullable=False, server_default="0"
    )
    completion_price_per_million: Mapped[Decimal] = mapped_column(
        PRICE, nullable=False, server_default="0"
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class AiRequest(IdentityMixin, TimestampMixin, Base):
    """One request to one model, answered or not.

    The prices are copied rather than read through `ai_model_id`, because a
    price is a fact about a moment: repricing a model in the roster must not
    rewrite what a run six weeks ago cost.
    """

    __tablename__ = "ai_requests"
    __table_args__ = (
        Index("ix_ai_requests_requested_at", "requested_at"),
        Index("ix_ai_requests_signal_id", "signal_id"),
        Index("ix_ai_requests_outcome", "outcome"),
    )

    ai_model_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_models.id", ondelete="SET NULL")
    )
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    purpose: Mapped[AiPurpose] = mapped_column(
        vocabulary(AiPurpose, "ai_purpose_values"), nullable=False
    )
    # Nullable: a classification request covers a batch and belongs to no single
    # signal. SET NULL rather than CASCADE, because deleting a signal must not
    # delete the record of what was spent on it.
    signal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("signals.id", ondelete="SET NULL")
    )
    batch_size: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    # Integer, not SmallInteger: a prompt can exceed 32767 tokens and a timeout
    # exceeds 32767 milliseconds, and a ledger that overflows is worse than none.
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    outcome: Mapped[AiOutcome] = mapped_column(
        vocabulary(AiOutcome, "ai_outcome_values"), nullable=False
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    prompt_price_per_million: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    completion_price_per_million: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(PRICE, nullable=False, server_default="0")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

In `packages/backend/src/episignal_backend/models/signal.py`, add the column
after `query_rule_id`:

```python
    # The disease this signal's extraction resolved to, when it resolved to one.
    # A foreign key rather than an id inside `ai_extraction`, because the
    # database cannot enforce a reference buried in JSONB.
    disease_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("diseases.id", ondelete="SET NULL")
    )
```

and add its index to `__table_args__`:

```python
        Index("ix_signals_disease_id", "disease_id"),
```

In `packages/backend/src/episignal_backend/models/__init__.py`, export the two
new models alongside the existing ones.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/models packages/backend/tests/test_models.py
git commit -m "feat: add the model roster, the request ledger, and the signal disease link"
```

---

## Task 12: Migration 20260827_0005

**Files:**
- Create: `database/migrations/versions/20260827_0005_ai_extraction.py`
- Test: `apps/api/tests/test_migrations.py`

Read `apps/api/tests/test_migrations.py` first. It never connects to a database:
it reads the revision chain through `ScriptDirectory`, and renders every other
assertion from offline SQL via `alembic --sql`. Two consequences bind this task:

1. `test_migrations_have_one_linear_head` asserts the head is `20260827_0004` and
   must be updated to `20260827_0005`. That is part of the failing test, not a
   later fix.
2. `test_offline_downgrade_drops_dependents_before_parents` renders a downgrade
   all the way to base, so it walks through 0005's `downgrade()`. Offline
   rendering has no connection, so the ledger check must be skipped when
   `op.get_context().as_sql` is true, or that existing test breaks. The guard
   protects a real rollback, and there is nothing to protect while emitting SQL
   for a human to read.

- [ ] **Step 1: Write the failing test**

In `apps/api/tests/test_migrations.py`, change the head assertion:

```python
    assert scripts.get_heads() == ["20260827_0005"]
```

and append:

```python
def test_fifth_revision_adds_the_model_roster_and_the_request_ledger() -> None:
    sql = render_offline("upgrade", "head")

    assert "create table ai_models" in sql
    assert "create table ai_requests" in sql
    assert "uq_ai_models_model_id" in sql
    assert "ck_ai_models_tier_range" in sql
    assert "ai_purpose_values" in sql
    assert "ai_outcome_values" in sql
    assert "ix_ai_requests_requested_at" in sql
    assert "add column disease_id" in sql
    assert "ix_signals_disease_id" in sql


def test_the_ledger_survives_retiring_a_model_or_deleting_a_signal() -> None:
    sql = render_offline("upgrade", "head")

    assert "fk_ai_requests_ai_model_id_ai_models" in sql
    assert "fk_ai_requests_signal_id_signals" in sql
    assert "on delete cascade" not in sql.split("create table ai_requests")[1][:2000]


def test_the_ai_downgrade_refuses_to_discard_the_ledger() -> None:
    root = Path(__file__).parents[3]
    source = (
        root
        / "database"
        / "migrations"
        / "versions"
        / "20260827_0005_ai_extraction.py"
    ).read_text(encoding="utf-8")

    assert "EPISIGNAL_ALLOW_AI_AUDIT_LOSS" in source
    assert "select count(*) from ai_requests" in source.lower()


def test_the_offline_downgrade_still_renders_through_the_ledger_guard() -> None:
    # The guard reads a table, which is impossible while rendering SQL offline.
    # If it ever runs in that mode, this test fails and so does the pre-existing
    # downgrade-ordering test.
    sql = render_offline("downgrade", "20260827_0005:20260827_0004")

    assert "drop table ai_requests" in sql
    assert "drop table ai_models" in sql
```

The revision file is read as text rather than imported: `20260827_0005` is not a
valid Python identifier, so the module cannot be imported by name, and Alembic
loads these files by path.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest apps/api/tests/test_migrations.py -v`
Expected: FAIL, the 0005 revision does not exist

- [ ] **Step 3: Write minimal implementation**

Create `database/migrations/versions/20260827_0005_ai_extraction.py`:

```python
"""add the AI model roster, the request ledger, and the signal disease link

Revision ID: 20260827_0005
Revises: 20260827_0004
Create Date: 2026-08-27

`ai_requests` is a ledger of numbers nobody can recompute after the fact:
tokens, latency, and the price in force at the time. Dropping it is destructive
in a way that dropping a derived table is not, so `downgrade` refuses while it
holds rows unless the operator says otherwise.

`signals.disease_id` is a real foreign key rather than an id inside
`ai_extraction`, because a reference buried in JSONB is one the database cannot
enforce and a deleted disease would leave it dangling in silence.
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0005"
down_revision: str | None = "20260827_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AI_PURPOSES = ("classification", "extraction")
AI_OUTCOMES = ("accepted", "rejected", "unavailable")
PRICE = sa.Numeric(12, 6)
AUDIT_LOSS_VARIABLE = "EPISIGNAL_ALLOW_AI_AUDIT_LOSS"


def upgrade() -> None:
    op.create_table(
        "ai_models",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tier", sa.SmallInteger(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("prompt_price_per_million", PRICE, server_default="0", nullable=False),
        sa.Column("completion_price_per_million", PRICE, server_default="0", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_models"),
        sa.UniqueConstraint("model_id", name="uq_ai_models_model_id"),
        sa.CheckConstraint("tier >= 1 AND tier <= 3", name="ck_ai_models_tier_range"),
    )
    op.create_index("ix_ai_models_tier", "ai_models", ["tier"])

    op.create_table(
        "ai_requests",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("ai_model_id", sa.Uuid(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("tier", sa.SmallInteger(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                *AI_PURPOSES,
                name="ai_purpose_values",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("signal_id", sa.Uuid(), nullable=True),
        sa.Column("batch_size", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("http_status", sa.SmallInteger(), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                *AI_OUTCOMES,
                name="ai_outcome_values",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("prompt_price_per_million", PRICE, nullable=False),
        sa.Column("completion_price_per_million", PRICE, nullable=False),
        sa.Column("cost_usd", PRICE, server_default="0", nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_requests"),
        sa.ForeignKeyConstraint(
            ["ai_model_id"],
            ["ai_models.id"],
            name="fk_ai_requests_ai_model_id_ai_models",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name="fk_ai_requests_signal_id_signals",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_ai_requests_requested_at", "ai_requests", ["requested_at"])
    op.create_index("ix_ai_requests_signal_id", "ai_requests", ["signal_id"])
    op.create_index("ix_ai_requests_outcome", "ai_requests", ["outcome"])

    op.add_column("signals", sa.Column("disease_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_signals_disease_id_diseases",
        "signals",
        "diseases",
        ["disease_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_signals_disease_id", "signals", ["disease_id"])


def downgrade() -> None:
    # The ledger is the only record of what inference cost. It cannot be
    # rebuilt from anything else in the database, so discarding it is a
    # separately authorized act rather than a side effect of rolling back.
    #
    # Skipped while rendering offline SQL: there is no connection to count with,
    # and nothing is destroyed by printing a statement for a human to read.
    if not op.get_context().as_sql:
        connection = op.get_bind()
        rows = connection.execute(sa.text("SELECT count(*) FROM ai_requests")).scalar_one()
        if rows and os.environ.get(AUDIT_LOSS_VARIABLE) != "1":
            raise RuntimeError(
                f"ai_requests holds {rows} cost rows that no other table can reproduce. "
                f"Export them first, then set {AUDIT_LOSS_VARIABLE}=1 to confirm the loss."
            )

    op.drop_index("ix_signals_disease_id", table_name="signals")
    op.drop_constraint("fk_signals_disease_id_diseases", "signals", type_="foreignkey")
    op.drop_column("signals", "disease_id")

    op.drop_index("ix_ai_requests_outcome", table_name="ai_requests")
    op.drop_index("ix_ai_requests_signal_id", table_name="ai_requests")
    op.drop_index("ix_ai_requests_requested_at", table_name="ai_requests")
    op.drop_table("ai_requests")

    op.drop_index("ix_ai_models_tier", table_name="ai_models")
    # No explicit constraint drop: the check constraint lives on the table and
    # goes with it.
    op.drop_table("ai_models")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest apps/api/tests/test_migrations.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database/migrations/versions/20260827_0005_ai_extraction.py apps/api/tests/test_migrations.py
git commit -m "feat: add the migration for the model roster and request ledger"
```

---

## Task 13: The seeded model roster

The three model ids below are the free OpenRouter roster as of this plan's date.
They are the first thing to verify against the live model list in task 20: free
endpoints are withdrawn without notice, and a dead id is a seed edit, not a code
change.

**Files:**
- Create: `database/seeds/ai_models.json`
- Modify: `packages/backend/src/episignal_backend/seeds.py`
- Test: `packages/backend/tests/test_seeds.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_seeds.py`:

```python
def test_the_seeded_roster_covers_all_three_tiers() -> None:
    from episignal_backend.seeds import load_ai_models

    models = load_ai_models()

    assert {model.tier for model in models} == {1, 2, 3}


def test_every_seeded_model_is_free() -> None:
    from episignal_backend.seeds import load_ai_models

    for model in load_ai_models():
        assert model.prompt_price_per_million == Decimal("0")
        assert model.completion_price_per_million == Decimal("0")


def test_no_two_seeded_models_share_an_identifier() -> None:
    from episignal_backend.seeds import load_ai_models

    identifiers = [model.model_id for model in load_ai_models()]

    assert len(identifiers) == len(set(identifiers))


def test_the_tiers_do_not_all_come_from_one_vendor() -> None:
    from episignal_backend.seeds import load_ai_models

    vendors = {model.model_id.split("/")[0] for model in load_ai_models()}

    assert len(vendors) > 1
```

Add `from decimal import Decimal` to the imports of that test module.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_seeds.py -k roster -v`
Expected: FAIL with `ImportError: cannot import name 'load_ai_models'`

- [ ] **Step 3: Write minimal implementation**

Create `database/seeds/ai_models.json`:

```json
[
  {
    "tier": 1,
    "model_id": "meta-llama/llama-3.3-70b-instruct:free",
    "label": "Llama 3.3 70B Instruct (free)",
    "prompt_price_per_million": "0",
    "completion_price_per_million": "0",
    "active": true
  },
  {
    "tier": 2,
    "model_id": "google/gemini-2.0-flash-exp:free",
    "label": "Gemini 2.0 Flash Experimental (free)",
    "prompt_price_per_million": "0",
    "completion_price_per_million": "0",
    "active": true
  },
  {
    "tier": 3,
    "model_id": "deepseek/deepseek-r1:free",
    "label": "DeepSeek R1 (free)",
    "prompt_price_per_million": "0",
    "completion_price_per_million": "0",
    "active": true
  }
]
```

The three tiers deliberately come from three vendors. A ladder whose rungs share
a family fails the same way on the same document, and an escalation that repeats
the first answer is an escalation that has bought nothing.

In `packages/backend/src/episignal_backend/seeds.py`, add the seed model
alongside the existing ones:

```python
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
```

Add a `load_ai_models()` loader in the same shape as the existing loaders,
reading `database/seeds/ai_models.json`, and seed the rows idempotently by
matching on `model_id`, exactly as diseases match on `slug`. Add `Decimal` to
the imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_seeds.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add database/seeds/ai_models.json packages/backend/src/episignal_backend/seeds.py packages/backend/tests/test_seeds.py
git commit -m "feat: seed the free model roster across three tiers"
```

---

## Task 14: Storage for the AI passes

**Files:**
- Create: `packages/backend/src/episignal_backend/ai/repository.py`
- Test: `packages/backend/tests/test_ai_repository.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_ai_repository.py`, reusing the `FakeSession`
and `FakeResult` pattern from `packages/backend/tests/test_dedupe_repository.py`:

```python
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, Update

from episignal_backend.ai.documents import AiRequestRecord, StoredExtraction, Verdict
from episignal_backend.ai.protocol import AiRepository
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.ai.schema import Extraction
from episignal_backend.db.types import AiOutcome, AiPurpose, ProcessingStatus, SignalType

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> Any:
        return self._value

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = results or []
        self.executed: list[Any] = []
        self.added: list[Any] = []

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return self._results.pop(0) if self._results else FakeResult(None)

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def extraction() -> Extraction:
    return Extraction.model_validate(
        {
            "signal_type": "outbreak_report",
            "summary": "Cholera outbreak reported in Luanda.",
            "confidence": 0.9,
        }
    )


def test_it_satisfies_the_storage_boundary() -> None:
    assert isinstance(SqlAlchemyAiRepository(FakeSession()), AiRepository)


def test_only_normalized_signals_are_offered_for_classification() -> None:
    session = FakeSession([FakeResult([])])

    SqlAlchemyAiRepository(session).awaiting_classification(limit=10)

    statement = session.executed[0]
    assert isinstance(statement, Select)
    rendered = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert ProcessingStatus.NORMALIZED.value in rendered
    assert ProcessingStatus.DUPLICATE.value not in rendered
    assert ProcessingStatus.NEEDS_REVIEW.value not in rendered
    assert "raw_text IS NOT NULL" in rendered


def test_only_relevant_classified_signals_are_offered_for_extraction() -> None:
    session = FakeSession([FakeResult([])])

    SqlAlchemyAiRepository(session).awaiting_extraction(limit=10)

    rendered = str(
        session.executed[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert ProcessingStatus.CLASSIFIED.value in rendered
    assert "public_health_relevant" in rendered


def test_a_verdict_writes_the_relevance_and_the_classified_status() -> None:
    session = FakeSession()

    SqlAlchemyAiRepository(session).record_classification(
        uuid4(),
        Verdict(
            is_public_health_relevant=False,
            signal_type=SignalType.UNKNOWN,
            relevance=0.04,
            model_id="vendor/model:free",
            decided_at=NOW,
        ),
    )

    statement = session.executed[0]
    assert isinstance(statement, Update)
    rendered = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert ProcessingStatus.CLASSIFIED.value in rendered


def test_an_accepted_extraction_writes_the_json_the_model_and_the_time() -> None:
    session = FakeSession()

    SqlAlchemyAiRepository(session).record_extraction(
        uuid4(),
        StoredExtraction(
            extraction=extraction(),
            disease_id=None,
            model_id="vendor/model:free",
            processed_at=NOW,
        ),
    )

    rendered = str(
        session.executed[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert ProcessingStatus.EXTRACTED.value in rendered


def test_a_cost_row_is_added_for_every_request() -> None:
    session = FakeSession()

    SqlAlchemyAiRepository(session).record_request(
        AiRequestRecord(
            ai_model_id=uuid4(),
            model_id="vendor/model:free",
            tier=1,
            purpose=AiPurpose.CLASSIFICATION,
            signal_id=None,
            batch_size=20,
            prompt_tokens=900,
            completion_tokens=120,
            latency_ms=740,
            http_status=200,
            outcome=AiOutcome.ACCEPTED,
            rejection_reason=None,
            prompt_price_per_million=Decimal("0"),
            completion_price_per_million=Decimal("0"),
            cost_usd=Decimal("0"),
            requested_at=NOW,
        )
    )

    assert len(session.added) == 1
    assert session.added[0].batch_size == 20


def test_a_disease_is_resolved_case_insensitively_or_not_at_all() -> None:
    identifier = uuid4()
    session = FakeSession([FakeResult(identifier), FakeResult(None)])
    repository = SqlAlchemyAiRepository(session)

    assert repository.resolve_disease("cholera") == identifier
    assert repository.resolve_disease("a disease nobody seeded") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ai_repository.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ai.repository'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ai/repository.py`:

```python
"""The storage boundary for the AI passes.

Deliberately unable to discover, fetch, or deduplicate: this pass reads stored
signals, asks a model about them, and writes back what it learned. It is also
the only module in `ai/` that imports SQLAlchemy, and it owns transactions on
behalf of the passes above it.
"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from episignal_backend.ai.documents import (
    AiRequestRecord,
    ClassifiableSignal,
    ExtractableSignal,
    ModelSpec,
    StoredExtraction,
    Verdict,
)
from episignal_backend.db.types import ProcessingStatus
from episignal_backend.models import AiModel, AiRequest, Disease, Signal

EXCERPT_CHARACTERS = 1200


class SqlAlchemyAiRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def models(self) -> Sequence[ModelSpec]:
        rows = self._session.execute(
            select(AiModel).where(AiModel.active.is_(True)).order_by(AiModel.tier)
        ).scalars()
        return tuple(
            ModelSpec(
                id=row.id,
                tier=row.tier,
                model_id=row.model_id,
                label=row.label,
                prompt_price_per_million=row.prompt_price_per_million,
                completion_price_per_million=row.completion_price_per_million,
            )
            for row in rows
        )

    def awaiting_classification(self, *, limit: int) -> Sequence[ClassifiableSignal]:
        # The enforcement of the first invariant: `duplicate`, `needs_review`,
        # and `fetched` are simply not selectable here, so no later change can
        # send one to a model by accident.
        rows = self._session.execute(
            select(Signal)
            .where(
                Signal.processing_status == ProcessingStatus.NORMALIZED,
                Signal.raw_text.is_not(None),
            )
            .order_by(Signal.first_seen_at)
            .limit(limit)
        ).scalars()
        return tuple(
            ClassifiableSignal(
                id=row.id,
                title=row.title,
                excerpt=(row.raw_text or "")[:EXCERPT_CHARACTERS],
            )
            for row in rows
        )

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        rows = self._session.execute(
            select(Signal)
            .where(
                Signal.processing_status == ProcessingStatus.CLASSIFIED,
                Signal.public_health_relevant.is_(True),
                Signal.raw_text.is_not(None),
            )
            .order_by(Signal.first_seen_at)
            .limit(limit)
        ).scalars()
        return tuple(
            ExtractableSignal(id=row.id, title=row.title, raw_text=row.raw_text or "")
            for row in rows
        )

    def resolve_disease(self, name: str) -> UUID | None:
        # Case-folded exact match against the reviewed vocabulary, including
        # synonyms. No fuzzy matching: guessing which disease was meant is how a
        # measles report becomes a cholera event.
        needle = " ".join(name.split()).lower()
        return self._session.execute(
            select(Disease.id).where(
                or_(
                    func.lower(Disease.canonical_name) == needle,
                    func.lower(Disease.slug) == needle,
                    Disease.synonyms.any(needle),
                )
            )
        ).scalar_one_or_none()

    def record_request(self, record: AiRequestRecord) -> None:
        self._session.add(
            AiRequest(
                ai_model_id=record.ai_model_id,
                model_id=record.model_id,
                tier=record.tier,
                purpose=record.purpose,
                signal_id=record.signal_id,
                batch_size=record.batch_size,
                prompt_tokens=record.prompt_tokens,
                completion_tokens=record.completion_tokens,
                latency_ms=record.latency_ms,
                http_status=record.http_status,
                outcome=record.outcome,
                rejection_reason=record.rejection_reason,
                prompt_price_per_million=record.prompt_price_per_million,
                completion_price_per_million=record.completion_price_per_million,
                cost_usd=record.cost_usd,
                requested_at=record.requested_at,
            )
        )

    def record_classification(self, signal_id: UUID, verdict: Verdict) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(
                processing_status=ProcessingStatus.CLASSIFIED,
                public_health_relevant=verdict.is_public_health_relevant,
                relevance_score=verdict.relevance,
                signal_type=verdict.signal_type,
                ai_model=verdict.model_id,
                ai_processed_at=verdict.decided_at,
            )
        )

    def record_extraction(self, signal_id: UUID, stored: StoredExtraction) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(
                processing_status=ProcessingStatus.EXTRACTED,
                ai_extraction=stored.extraction.model_dump(mode="json"),
                ai_model=stored.model_id,
                ai_processed_at=stored.processed_at,
                disease_id=stored.disease_id,
                signal_type=stored.extraction.signal_type,
                summary=stored.extraction.summary,
            )
        )

    def mark_needs_review(self, signal_id: UUID) -> None:
        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(processing_status=ProcessingStatus.NEEDS_REVIEW)
        )

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ai_repository.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/repository.py packages/backend/tests/test_ai_repository.py
git commit -m "feat: add storage for classification, extraction, and cost rows"
```

---
## Task 15: One climb of the ladder

Both passes escalate the same way, so the climb lives in one place and each pass
supplies only what differs: how to build the request, and how to accept an
answer. Keeping this out of the two passes is what stops classification and
extraction drifting into two different escalation policies.

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/ladder.py`
- Test: `packages/backend/tests/test_ai_ladder.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_ai_ladder.py`:

```python
from episignal_backend.ai.documents import ChatRequest, ChatResponse
from episignal_backend.ai.ladder import Attempt, ClimbOutcome, climb
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.ai.validate import RejectionReason, Rejected


class ScriptedModel:
    """Answers from a script, one entry per call, so a climb is reproducible."""

    def __init__(self, script: list[object]) -> None:
        self.script = script
        self.asked: list[str] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.asked.append(request.model_id)
        answer = self.script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return ChatResponse(
            content=str(answer), usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
            http_status=200, latency_ms=5,
        )


def request_for(spec: ModelSpec) -> ChatRequest:
    return ChatRequest(model_id=spec.model_id, system="s", user="u")


def accept_ok(content: str) -> str:
    if content != "ok":
        raise Rejected(RejectionReason.SHAPE, content)
    return content


def budget() -> RunBudget:
    return RunBudget(Guards(max_requests=10, max_cost_usd=Decimal("1")))


def test_a_good_answer_at_the_first_tier_makes_one_request() -> None:
    model = ScriptedModel(["ok"])
    recorded: list[Attempt] = []

    result = climb(
        ladder=Ladder.build((spec(1), spec(2), spec(3)), max_tier=3),
        budget=budget(),
        model=model,
        request_for=request_for,
        accept=accept_ok,
        on_attempt=recorded.append,
    )

    assert result.outcome is ClimbOutcome.ACCEPTED
    assert result.value == "ok"
    assert len(model.asked) == 1
    assert len(recorded) == 1


def test_a_rejected_answer_escalates_to_the_next_tier() -> None:
    model = ScriptedModel(["bad", "ok"])

    result = climb(
        ladder=Ladder.build((spec(1), spec(2), spec(3)), max_tier=3),
        budget=budget(),
        model=model,
        request_for=request_for,
        accept=accept_ok,
        on_attempt=lambda attempt: None,
    )

    assert result.outcome is ClimbOutcome.ACCEPTED
    assert model.asked == ["vendor/model-tier-1:free", "vendor/model-tier-2:free"]


def test_rejection_at_every_tier_ends_the_climb_as_rejected() -> None:
    model = ScriptedModel(["bad", "bad", "bad"])

    result = climb(
        ladder=Ladder.build((spec(1), spec(2), spec(3)), max_tier=3),
        budget=budget(),
        model=model,
        request_for=request_for,
        accept=accept_ok,
        on_attempt=lambda attempt: None,
    )

    assert result.outcome is ClimbOutcome.REJECTED
    assert result.reason == RejectionReason.SHAPE.value
    assert len(model.asked) == 3


def test_an_unreachable_provider_at_every_tier_is_not_a_rejection() -> None:
    model = ScriptedModel([ModelUnavailable("429"), ModelUnavailable("429")])

    result = climb(
        ladder=Ladder.build((spec(1), spec(2)), max_tier=3),
        budget=budget(),
        model=model,
        request_for=request_for,
        accept=accept_ok,
        on_attempt=lambda attempt: None,
    )

    assert result.outcome is ClimbOutcome.UNAVAILABLE


def test_a_climb_records_a_cost_row_for_every_attempt_including_failures() -> None:
    model = ScriptedModel(["bad", ModelUnavailable("429"), "ok"])
    recorded: list[Attempt] = []

    climb(
        ladder=Ladder.build((spec(1), spec(2), spec(3)), max_tier=3),
        budget=budget(),
        model=model,
        request_for=request_for,
        accept=accept_ok,
        on_attempt=recorded.append,
    )

    assert [attempt.outcome.value for attempt in recorded] == [
        "rejected",
        "unavailable",
        "accepted",
    ]


def test_an_exhausted_budget_stops_the_climb_before_it_starts() -> None:
    model = ScriptedModel(["ok"])
    spent = RunBudget(Guards(max_requests=1, max_cost_usd=Decimal("1")))
    spent.record(Decimal("0"))

    result = climb(
        ladder=Ladder.build((spec(1),), max_tier=3),
        budget=spent,
        model=model,
        request_for=request_for,
        accept=accept_ok,
        on_attempt=lambda attempt: None,
    )

    assert result.outcome is ClimbOutcome.GUARD
    assert model.asked == []


def test_the_language_of_the_document_never_appears_in_the_climb() -> None:
    import inspect

    from episignal_backend.ai import ladder as module

    source = inspect.getsource(module)

    assert "language" not in source
    assert "script" not in source
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ai_ladder.py -k climb -v`
Expected: FAIL with `ImportError: cannot import name 'climb'`

- [ ] **Step 3: Write minimal implementation**

Append to `packages/backend/src/episignal_backend/ai/ladder.py`:

```python
T = TypeVar("T")


class ClimbOutcome(StrEnum):
    ACCEPTED = "accepted"
    # Every tier answered and no answer could be trusted. The signal is now
    # known to be beyond this ladder, so it goes for review.
    REJECTED = "rejected"
    # No tier answered. Nothing is known about the signal, so it must be left
    # exactly as it was and tried again later.
    UNAVAILABLE = "unavailable"
    GUARD = "guard"


@dataclass(frozen=True)
class Attempt:
    """One request, as the cost row will describe it."""

    spec: ModelSpec
    usage: TokenUsage
    http_status: int | None
    latency_ms: int
    outcome: AiOutcome
    reason: str | None
    cost: Decimal


@dataclass(frozen=True)
class ClimbResult(Generic[T]):
    outcome: ClimbOutcome
    value: T | None = None
    reason: str | None = None


def climb(
    *,
    ladder: Ladder,
    budget: RunBudget,
    model: ChatModel,
    request_for: Callable[[ModelSpec], ChatRequest],
    accept: Callable[[str], T],
    on_attempt: Callable[[Attempt], None],
) -> ClimbResult[T]:
    """Ask each rung in turn until one answer passes `accept`.

    `accept` raises `Rejected`; the provider raises `ModelUnavailable`. The two
    are kept apart all the way out, because one means the answer was wrong and
    the other means there was no answer.
    """
    reason: str | None = None
    answered = False

    for spec in ladder.rungs:
        if budget.exhausted:
            return ClimbResult(outcome=ClimbOutcome.GUARD, reason=reason)

        try:
            response = model.complete(request_for(spec))
        except ModelUnavailable as error:
            reason = str(error)
            budget.record(Decimal("0"))
            on_attempt(
                Attempt(
                    spec=spec,
                    usage=TokenUsage(),
                    http_status=None,
                    latency_ms=0,
                    outcome=AiOutcome.UNAVAILABLE,
                    reason=reason,
                    cost=Decimal("0"),
                )
            )
            continue

        answered = True
        amount = cost_usd(response.usage, spec)
        budget.record(amount)

        try:
            value = accept(response.content)
        except Rejected as rejection:
            reason = rejection.reason.value
            on_attempt(
                Attempt(
                    spec=spec,
                    usage=response.usage,
                    http_status=response.http_status,
                    latency_ms=response.latency_ms,
                    outcome=AiOutcome.REJECTED,
                    reason=reason,
                    cost=amount,
                )
            )
            continue

        on_attempt(
            Attempt(
                spec=spec,
                usage=response.usage,
                http_status=response.http_status,
                latency_ms=response.latency_ms,
                outcome=AiOutcome.ACCEPTED,
                reason=None,
                cost=amount,
            )
        )
        return ClimbResult(outcome=ClimbOutcome.ACCEPTED, value=value)

    ending = ClimbOutcome.REJECTED if answered else ClimbOutcome.UNAVAILABLE
    return ClimbResult(outcome=ending, reason=reason)


def cost_row(
    attempt: Attempt,
    *,
    purpose: AiPurpose,
    signal_id: UUID | None,
    batch_size: int,
    at: datetime,
) -> AiRequestRecord:
    """One attempt, as the ledger records it.

    Shared by both passes on purpose: two passes that each wrote their own cost
    row would eventually record different things about the same event, and the
    ledger would stop being comparable with itself.
    """
    return AiRequestRecord(
        ai_model_id=attempt.spec.id,
        model_id=attempt.spec.model_id,
        tier=attempt.spec.tier,
        purpose=purpose,
        signal_id=signal_id,
        batch_size=batch_size,
        prompt_tokens=attempt.usage.prompt_tokens,
        completion_tokens=attempt.usage.completion_tokens,
        latency_ms=attempt.latency_ms,
        http_status=attempt.http_status,
        outcome=attempt.outcome,
        rejection_reason=attempt.reason,
        prompt_price_per_million=attempt.spec.prompt_price_per_million,
        completion_price_per_million=attempt.spec.completion_price_per_million,
        cost_usd=attempt.cost,
        requested_at=at,
    )
```

Extend the imports at the top of the same file:

```python
from collections.abc import Callable, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID

from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatRequest,
    ModelSpec,
    TokenUsage,
)
from episignal_backend.ai.protocol import ChatModel, ModelUnavailable, NoModelsConfigured
from episignal_backend.ai.validate import Rejected
from episignal_backend.db.types import AiOutcome, AiPurpose
```

Add one more test for the shared cost row, in the same file:

```python
def test_a_cost_row_carries_the_price_that_was_in_force() -> None:
    from datetime import UTC, datetime

    from episignal_backend.ai.ladder import cost_row
    from episignal_backend.db.types import AiOutcome, AiPurpose

    priced = spec(2, prompt="0.100000", completion="0.400000")
    attempt = Attempt(
        spec=priced,
        usage=TokenUsage(prompt_tokens=1_000_000, completion_tokens=0),
        http_status=200,
        latency_ms=12,
        outcome=AiOutcome.ACCEPTED,
        reason=None,
        cost=Decimal("0.100000"),
    )

    row = cost_row(
        attempt,
        purpose=AiPurpose.EXTRACTION,
        signal_id=None,
        batch_size=1,
        at=datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
    )

    assert row.prompt_price_per_million == Decimal("0.100000")
    assert row.cost_usd == Decimal("0.100000")
```

The last test in step 1 is a guard, not a formality: it fails the moment anyone
adds a language or script condition to the escalation policy, which the design
forbids.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ai_ladder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/ladder.py packages/backend/tests/test_ai_ladder.py
git commit -m "feat: climb the model ladder on rejection, not on language"
```

---

## Task 16: The classification pass

**Files:**
- Create: `packages/backend/src/episignal_backend/ai/classify.py`
- Test: `packages/backend/tests/test_ai_classify.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_ai_classify.py`:

```python
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from episignal_backend.ai.classify import ClassificationResult, run_classification
from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatRequest,
    ChatResponse,
    ClassifiableSignal,
    ExtractableSignal,
    ModelSpec,
    StoredExtraction,
    TokenUsage,
    Verdict,
)
from episignal_backend.ai.ladder import Guards
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.db.types import AiOutcome

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)
FIRST = UUID("b3f1c2d4-0000-4000-8000-000000000001")
SECOND = UUID("b3f1c2d4-0000-4000-8000-000000000002")


def spec(tier: int) -> ModelSpec:
    return ModelSpec(
        id=uuid4(),
        tier=tier,
        model_id=f"vendor{tier}/model:free",
        label=f"Tier {tier}",
        prompt_price_per_million=Decimal("0"),
        completion_price_per_million=Decimal("0"),
    )


class FakeRepository:
    def __init__(self, pending: Sequence[ClassifiableSignal]) -> None:
        self._pending = tuple(pending)
        self.requests: list[AiRequestRecord] = []
        self.verdicts: dict[UUID, Verdict] = {}
        self.reviewed: list[UUID] = []
        self.commits = 0

    def models(self) -> Sequence[ModelSpec]:
        return (spec(1), spec(2), spec(3))

    def awaiting_classification(self, *, limit: int) -> Sequence[ClassifiableSignal]:
        return self._pending[:limit]

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        return ()

    def resolve_disease(self, name: str) -> UUID | None:
        return None

    def record_request(self, record: AiRequestRecord) -> None:
        self.requests.append(record)

    def record_classification(self, signal_id: UUID, verdict: Verdict) -> None:
        self.verdicts[signal_id] = verdict

    def record_extraction(self, signal_id: UUID, stored: StoredExtraction) -> None:
        raise AssertionError("the classification pass must not write an extraction")

    def mark_needs_review(self, signal_id: UUID) -> None:
        self.reviewed.append(signal_id)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None


class ScriptedModel:
    def __init__(self, script: list[object]) -> None:
        self.script = script
        self.asked: list[str] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.asked.append(request.model_id)
        answer = self.script.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return ChatResponse(
            content=str(answer),
            usage=TokenUsage(prompt_tokens=800, completion_tokens=60),
            http_status=200,
            latency_ms=310,
        )


def signal(identifier: UUID, title: str) -> ClassifiableSignal:
    return ClassifiableSignal(id=identifier, title=title, excerpt="Health officials said.")


def answer(*verdicts: dict[str, object]) -> str:
    return json.dumps({"results": list(verdicts)})


def verdict(identifier: UUID, relevant: bool) -> dict[str, object]:
    return {
        "id": str(identifier),
        "is_public_health_relevant": relevant,
        "signal_type": "outbreak_report" if relevant else "unknown",
        "relevance": 0.91 if relevant else 0.03,
    }


def guards() -> Guards:
    return Guards(max_requests=50, max_cost_usd=Decimal("1"))


def test_a_relevant_and_an_irrelevant_signal_are_both_decided() -> None:
    repository = FakeRepository(
        (signal(FIRST, "Cholera cases rise"), signal(SECOND, "City wins the cup"))
    )
    model = ScriptedModel([answer(verdict(FIRST, True), verdict(SECOND, False))])

    result = run_classification(
        repository, model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    assert result == ClassificationResult(
        examined=2, relevant=1, irrelevant=1, reviewed=0, unavailable=0, requests=1
    )
    assert repository.verdicts[FIRST].is_public_health_relevant is True
    assert repository.verdicts[SECOND].is_public_health_relevant is False


def test_an_id_that_was_never_sent_escalates_the_whole_batch() -> None:
    repository = FakeRepository((signal(FIRST, "Cholera cases rise"),))
    model = ScriptedModel(
        [answer(verdict(uuid4(), True)), answer(verdict(FIRST, True))]
    )

    run_classification(
        repository, model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    assert len(model.asked) == 2
    assert repository.verdicts[FIRST].is_public_health_relevant is True


def test_rejection_at_every_tier_sends_the_whole_batch_for_review() -> None:
    repository = FakeRepository((signal(FIRST, "a"), signal(SECOND, "b")))
    model = ScriptedModel(["nonsense", "nonsense", "nonsense"])

    result = run_classification(
        repository, model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    assert sorted(repository.reviewed) == sorted([FIRST, SECOND])
    assert result.reviewed == 2


def test_an_unreachable_provider_leaves_the_signals_untouched() -> None:
    repository = FakeRepository((signal(FIRST, "a"),))
    model = ScriptedModel([ModelUnavailable("429"), ModelUnavailable("429"), ModelUnavailable("429")])

    run_classification(
        repository, model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    assert repository.verdicts == {}
    assert repository.reviewed == []


def test_every_attempt_writes_a_cost_row_naming_the_batch_size() -> None:
    repository = FakeRepository((signal(FIRST, "a"), signal(SECOND, "b")))
    model = ScriptedModel(["nonsense", answer(verdict(FIRST, True), verdict(SECOND, True))])

    run_classification(
        repository, model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    assert [record.outcome for record in repository.requests] == [
        AiOutcome.REJECTED,
        AiOutcome.ACCEPTED,
    ]
    assert {record.batch_size for record in repository.requests} == {2}
    assert all(record.signal_id is None for record in repository.requests)


def test_the_batch_size_splits_the_queue_into_separate_requests() -> None:
    repository = FakeRepository((signal(FIRST, "a"), signal(SECOND, "b")))
    model = ScriptedModel([answer(verdict(FIRST, True)), answer(verdict(SECOND, True))])

    result = run_classification(
        repository, model, guards=guards(), batch_size=1, limit=100, now=lambda: NOW
    )

    assert result.requests == 2
    assert len(model.asked) == 2


def test_a_reached_request_guard_stops_the_pass_and_reports_it() -> None:
    repository = FakeRepository((signal(FIRST, "a"), signal(SECOND, "b")))
    model = ScriptedModel([answer(verdict(FIRST, True))])

    result = run_classification(
        repository,
        model,
        guards=Guards(max_requests=1, max_cost_usd=Decimal("1")),
        batch_size=1,
        limit=100,
        now=lambda: NOW,
    )

    assert result.stopped_early is True
    assert SECOND not in repository.verdicts


def test_an_empty_queue_makes_no_request() -> None:
    repository = FakeRepository(())
    model = ScriptedModel([])

    result = run_classification(
        repository, model, guards=guards(), batch_size=20, limit=100, now=lambda: NOW
    )

    assert result.examined == 0
    assert model.asked == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ai_classify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ai.classify'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ai/classify.py`:

```python
"""The batched relevance pass.

Batched because relevance is decided from a title and an opening, and one
request can carry many of those. The batch is also the unit of trust: an answer
that does not address exactly the batch it was given is discarded whole.

This module imports neither SQLAlchemy nor httpx.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatRequest,
    ClassifiableSignal,
    ModelSpec,
    Verdict,
)
from episignal_backend.ai.ladder import Attempt, ClimbOutcome, Guards, Ladder, RunBudget, climb
from episignal_backend.ai.prompts import classification_prompt
from episignal_backend.ai.protocol import AiRepository, ChatModel
from episignal_backend.ai.schema import ClassificationResponse
from episignal_backend.ai.validate import validate_classification
from episignal_backend.db.types import AiPurpose

DEFAULT_BATCH_SIZE = 20
DEFAULT_LIMIT = 100
DEFAULT_MAX_TIER = 3
DEFAULT_MAX_INPUT_CHARACTERS = 12000

logger = logging.getLogger("episignal_backend.ai.classify")


@dataclass(frozen=True)
class ClassificationResult:
    examined: int = 0
    relevant: int = 0
    irrelevant: int = 0
    reviewed: int = 0
    # Signals no tier could be asked about. Not failures and not decisions:
    # they are simply still waiting.
    unavailable: int = 0
    requests: int = 0
    stopped_early: bool = False


def _batches(
    pending: Sequence[ClassifiableSignal], size: int
) -> list[Sequence[ClassifiableSignal]]:
    return [pending[start : start + size] for start in range(0, len(pending), size)]


def run_classification(
    repository: AiRepository,
    model: ChatModel,
    *,
    guards: Guards,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int = DEFAULT_LIMIT,
    max_tier: int = DEFAULT_MAX_TIER,
    max_input_characters: int = DEFAULT_MAX_INPUT_CHARACTERS,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ClassificationResult:
    ladder = Ladder.build(repository.models(), max_tier=max_tier)
    budget = RunBudget(guards)
    pending = repository.awaiting_classification(limit=limit)

    relevant = 0
    irrelevant = 0
    reviewed = 0
    unavailable = 0
    requests = 0
    stopped_early = False

    for batch in _batches(pending, batch_size):
        identifiers = tuple(signal.id for signal in batch)
        system, user = classification_prompt(batch, max_characters=max_input_characters)
        attempts: list[Attempt] = []

        result = climb(
            ladder=ladder,
            budget=budget,
            model=model,
            request_for=lambda spec: ChatRequest(
                model_id=spec.model_id, system=system, user=user
            ),
            accept=lambda content: validate_classification(content, identifiers),
            on_attempt=attempts.append,
        )
        requests += len(attempts)

        try:
            at = now()
            for attempt in attempts:
                repository.record_request(
                    cost_row(
                        attempt,
                        purpose=AiPurpose.CLASSIFICATION,
                        signal_id=None,
                        batch_size=len(batch),
                        at=at,
                    )
                )

            if result.outcome is ClimbOutcome.ACCEPTED and result.value is not None:
                # The accepted answer is always the last attempt, which is the
                # rung whose name belongs on every signal it decided.
                decided = _write(repository, result.value, attempts[-1].spec.model_id, at)
                relevant += decided
                irrelevant += len(batch) - decided
            elif result.outcome is ClimbOutcome.REJECTED:
                for signal in batch:
                    repository.mark_needs_review(signal.id)
                reviewed += len(batch)
            else:
                # GUARD or UNAVAILABLE: nothing was learned about these signals,
                # so nothing is written about them and the next run sees them
                # unchanged. The cost rows above are still committed, because
                # the attempt itself is a fact.
                unavailable += len(batch)

            repository.commit()
        except Exception as error:
            repository.rollback()
            logger.error("Could not store a classification batch (%s)", type(error).__name__)

        if result.outcome is ClimbOutcome.GUARD:
            stopped_early = True
            break

    return ClassificationResult(
        examined=len(pending),
        relevant=relevant,
        irrelevant=irrelevant,
        reviewed=reviewed,
        unavailable=unavailable,
        requests=requests,
        stopped_early=stopped_early,
    )


def _write(
    repository: AiRepository, response: ClassificationResponse, model_id: str, at: datetime
) -> int:
    relevant = 0
    for entry in response.results:
        repository.record_classification(
            entry.id,
            Verdict(
                is_public_health_relevant=entry.is_public_health_relevant,
                signal_type=entry.signal_type,
                relevance=entry.relevance,
                model_id=model_id,
                decided_at=at,
            ),
        )
        relevant += 1 if entry.is_public_health_relevant else 0
    return relevant
```

Import `cost_row` from `ai/ladder.py` alongside `climb`; the cost row is written
identically by both passes and lives in one place.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ai_classify.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/classify.py packages/backend/tests/test_ai_classify.py
git commit -m "feat: decide relevance in batches and record what each batch cost"
```

---

## Task 17: The extraction pass

**Files:**
- Create: `packages/backend/src/episignal_backend/ai/extract.py`
- Create: `packages/backend/tests/fixtures/ai_multilingual_body.txt`
- Create: `packages/backend/tests/fixtures/ai_extraction_response.json`
- Test: `packages/backend/tests/test_ai_extract.py`

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/fixtures/ai_multilingual_body.txt`:

```text
LUANDA — Le ministère angolais de la santé a déclaré lundi que l'épidémie de
choléra dans la province de Luanda s'était aggravée, avec 327 cas confirmés
enregistrés depuis le début du mois d'août.

Les autorités ont indiqué que 14 personnes sont mortes. Le ministère a précisé
que tous les cas avaient été contractés localement. Les chiffres sont arrêtés au
25 août 2026.
```

Create `packages/backend/tests/fixtures/ai_extraction_response.json`:

```json
{
  "signal_type": "outbreak_report",
  "summary": "Angola's health ministry reports a growing cholera outbreak in Luanda province.",
  "disease": { "name": "Cholera", "confidence": 0.97 },
  "pathogen": { "name": "Vibrio cholerae", "confidence": 0.88 },
  "locations": [
    { "role": "primary", "country": "Angola", "admin1": "Luanda", "place_name": "Luanda" }
  ],
  "epidemiology": {
    "confirmed_cases": { "value": 327, "source_span": "327 confirmed cases" },
    "total_cases": { "value": 400, "source_span": "400 cases in total" },
    "deaths": { "value": 14, "source_span": "14 people have died" }
  },
  "dates": { "data_as_of": "2026-08-25" },
  "transmission": {
    "local_transmission": { "value": true, "source_span": "all cases were acquired locally" }
  },
  "confidence": 0.94
}
```

Create `packages/backend/tests/test_ai_extract.py`, reusing `FakeRepository` and
`ScriptedModel` from `test_ai_classify.py` by importing them from that module:

```python
import json
from pathlib import Path
from uuid import UUID, uuid4

from episignal_backend.ai.extract import ExtractionResult, run_extraction
from episignal_backend.ai.documents import ExtractableSignal
from episignal_backend.ai.ladder import Guards
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.db.types import AiOutcome, AiPurpose

FIXTURES = Path(__file__).parent / "fixtures"
BODY = (FIXTURES / "ai_outbreak_body.txt").read_text(encoding="utf-8")
FRENCH = (FIXTURES / "ai_multilingual_body.txt").read_text(encoding="utf-8")
GOOD = (FIXTURES / "ai_extraction_response.json").read_text(encoding="utf-8")
UNGROUNDED = (FIXTURES / "ai_ungrounded_response.json").read_text(encoding="utf-8")
FIRST = UUID("b3f1c2d4-0000-4000-8000-000000000001")
```

Then the fake repository for this pass, and the helpers the tests share:

```python
SECOND = UUID("b3f1c2d4-0000-4000-8000-000000000002")
CHOLERA = UUID("b3f1c2d4-0000-4000-8000-0000000000ff")

FRENCH_ANSWER = json.dumps(
    {
        "signal_type": "outbreak_report",
        "summary": "Cholera outbreak in Luanda province, Angola.",
        "disease": {"name": "Cholera", "confidence": 0.96},
        "locations": [{"role": "primary", "country": "Angola", "place_name": "Luanda"}],
        "epidemiology": {
            "confirmed_cases": {"value": 327, "source_span": "327 cas confirmés"},
            "deaths": {"value": 14, "source_span": "14 personnes sont mortes"},
        },
        "dates": {"data_as_of": "2026-08-25"},
        "transmission": {
            "local_transmission": {
                "value": True,
                "source_span": "tous les cas avaient été contractés localement",
            }
        },
        "confidence": 0.93,
    }
)


class ExtractRepository(FakeRepository):
    def __init__(
        self,
        pending: Sequence[ExtractableSignal],
        diseases: dict[str, UUID] | None = None,
    ) -> None:
        super().__init__(())
        self._pending = tuple(pending)
        self._diseases = diseases or {}
        self.stored: dict[UUID, StoredExtraction] = {}

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        return self._pending[:limit]

    def resolve_disease(self, name: str) -> UUID | None:
        return self._diseases.get(name.lower())

    def record_classification(self, signal_id: UUID, verdict: Verdict) -> None:
        raise AssertionError("the extraction pass must not write a verdict")

    def record_extraction(self, signal_id: UUID, stored: StoredExtraction) -> None:
        self.stored[signal_id] = stored


def english(identifier: UUID = FIRST) -> ExtractableSignal:
    return ExtractableSignal(id=identifier, title="Cholera cases rise", raw_text=BODY)


def french() -> ExtractableSignal:
    return ExtractableSignal(id=SECOND, title="Le choléra progresse", raw_text=FRENCH)


def run(repository: ExtractRepository, model: ScriptedModel) -> ExtractionResult:
    return run_extraction(
        repository, model, guards=guards(), limit=100, now=lambda: NOW
    )
```

`FakeRepository`, `ScriptedModel`, `guards`, and `NOW` are imported from
`test_ai_classify.py`; `Sequence`, `Verdict`, and `StoredExtraction` come from
their usual modules.

Now the tests:

```python
def test_a_grounded_extraction_is_stored_with_its_model_and_time() -> None:
    repository = ExtractRepository((english(),))

    result = run(repository, ScriptedModel([GOOD]))

    assert result == ExtractionResult(
        examined=1, extracted=1, reviewed=0, unavailable=0, requests=1, stopped_early=False
    )
    assert repository.stored[FIRST].processed_at == NOW
    assert repository.stored[FIRST].model_id == "vendor1/model:free"


def test_the_resolved_disease_is_attached_when_the_vocabulary_knows_it() -> None:
    repository = ExtractRepository((english(),), diseases={"cholera": CHOLERA})

    run(repository, ScriptedModel([GOOD]))

    assert repository.stored[FIRST].disease_id == CHOLERA


def test_an_unknown_disease_leaves_the_link_empty_rather_than_guessing() -> None:
    repository = ExtractRepository((english(),), diseases={})

    run(repository, ScriptedModel([GOOD]))

    assert repository.stored[FIRST].disease_id is None


def test_an_ungrounded_answer_escalates_and_the_signal_is_not_written() -> None:
    repository = ExtractRepository((english(),))
    model = ScriptedModel([UNGROUNDED, GOOD])

    run(repository, model)

    assert len(model.asked) == 2
    assert repository.stored[FIRST].extraction.epidemiology.deaths is not None
    assert repository.stored[FIRST].extraction.epidemiology.deaths.value == 14


def test_an_ungrounded_answer_at_every_tier_sends_one_signal_for_review() -> None:
    repository = ExtractRepository((english(),))

    result = run(repository, ScriptedModel([UNGROUNDED, UNGROUNDED, UNGROUNDED]))

    assert repository.reviewed == [FIRST]
    assert repository.stored == {}
    assert result.reviewed == 1


def test_a_french_article_with_a_grounded_answer_makes_exactly_one_request() -> None:
    repository = ExtractRepository((french(),))
    model = ScriptedModel([FRENCH_ANSWER])

    result = run(repository, model)

    assert len(model.asked) == 1
    assert result.extracted == 1


def test_an_unreachable_provider_leaves_the_signal_selectable() -> None:
    repository = ExtractRepository((english(),))
    model = ScriptedModel(
        [ModelUnavailable("429"), ModelUnavailable("429"), ModelUnavailable("429")]
    )

    run(repository, model)

    assert repository.reviewed == []
    assert repository.stored == {}


def test_each_extraction_cost_row_names_its_single_signal() -> None:
    repository = ExtractRepository((english(),))

    run(repository, ScriptedModel([UNGROUNDED, GOOD]))

    assert [record.outcome for record in repository.requests] == [
        AiOutcome.REJECTED,
        AiOutcome.ACCEPTED,
    ]
    assert all(record.purpose is AiPurpose.EXTRACTION for record in repository.requests)
    assert all(record.signal_id == FIRST for record in repository.requests)
    assert all(record.batch_size == 1 for record in repository.requests)


def test_one_failing_signal_does_not_stop_the_rest_of_the_queue() -> None:
    repository = ExtractRepository((english(), french()))
    model = ScriptedModel([UNGROUNDED, UNGROUNDED, UNGROUNDED, FRENCH_ANSWER])

    result = run(repository, model)

    assert result.extracted == 1
    assert result.reviewed == 1


def test_each_signal_is_committed_on_its_own() -> None:
    repository = ExtractRepository((english(), french()))

    run(repository, ScriptedModel([GOOD, FRENCH_ANSWER]))

    assert repository.commits == 2
```

The French test is the one that proves decision 5. Its spans are copied out of
`ai_multilingual_body.txt`, so the answer is grounded in French text and is
accepted at tier one. If it ever needs two requests, the escalation policy has
started reading the alphabet.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_ai_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ai.extract'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ai/extract.py` in the shape of
`classify.py`, differing only where the design says it differs:

- one signal per request, so `batch_size` is always 1 and `signal_id` is always
  set on the cost row;
- `purpose` is `AiPurpose.EXTRACTION`;
- `accept` is `lambda content: validate_extraction(content, signal.raw_text, min_confidence=min_confidence)`;
- on acceptance, resolve the disease through `repository.resolve_disease` when
  the extraction names one, then `record_extraction`;
- `repository.commit()` after each signal, and `repository.rollback()` in the
  `except` around each signal, so one bad row cannot lose the run;
- on `ClimbOutcome.REJECTED`, `mark_needs_review` for that one signal;
- on `ClimbOutcome.UNAVAILABLE`, write nothing about the signal and count it
  as `unavailable`;
- on `ClimbOutcome.GUARD`, set `stopped_early` and break out of the loop.

Return:

```python
@dataclass(frozen=True)
class ExtractionResult:
    examined: int = 0
    extracted: int = 0
    reviewed: int = 0
    unavailable: int = 0
    requests: int = 0
    stopped_early: bool = False
```

Use `cost_row` from `ai/ladder.py` with `purpose=AiPurpose.EXTRACTION`,
`signal_id=signal.id`, and `batch_size=1`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_ai_extract.py packages/backend/tests/test_ai_classify.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai packages/backend/tests/test_ai_extract.py packages/backend/tests/fixtures
git commit -m "feat: extract grounded epidemiological facts one signal at a time"
```

---

## Task 18: The OpenRouter adapter

**Files:**
- Create: `packages/backend/src/episignal_backend/ai/openrouter.py`
- Test: `packages/backend/tests/test_openrouter.py`

Follow `packages/backend/src/episignal_backend/ingestion/gdelt/api.py`: an
injected `httpx.Client`, an injected `sleep`, a retry set, and a bounded attempt
count.

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_openrouter.py`:

```python
import json

import httpx
import pytest

from episignal_backend.ai.documents import ChatRequest
from episignal_backend.ai.openrouter import OpenRouterChatModel
from episignal_backend.ai.protocol import ModelUnavailable

REQUEST = ChatRequest(model_id="vendor/model:free", system="rules", user="article")


def model(handler: object, sleeps: list[float] | None = None) -> OpenRouterChatModel:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenRouterChatModel(
        api_key="test-key", client=client, sleep=(sleeps or []).append
    )


def body(content: str, prompt: int = 900, completion: int = 120) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


def test_a_successful_call_returns_the_content_and_the_usage() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body('{"ok": true}'))

    response = model(handler).complete(REQUEST)

    assert response.content == '{"ok": true}'
    assert response.usage.prompt_tokens == 900
    assert response.http_status == 200
    assert response.latency_ms >= 0


def test_the_request_names_the_model_and_carries_both_messages() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=body("{}"))

    model(handler).complete(REQUEST)

    assert seen[0]["model"] == "vendor/model:free"
    assert [message["role"] for message in seen[0]["messages"]] == ["system", "user"]


def test_the_api_key_travels_in_the_authorization_header() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json=body("{}"))

    model(handler).complete(REQUEST)

    assert seen[0] == "Bearer test-key"


def test_a_rate_limit_is_retried_and_then_succeeds() -> None:
    statuses = [429, 200]

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses.pop(0)
        return httpx.Response(status, json=body("{}") if status == 200 else {})

    sleeps: list[float] = []
    response = model(handler, sleeps).complete(REQUEST)

    assert response.http_status == 200
    assert len(sleeps) == 1


def test_a_persistent_rate_limit_is_unavailable_not_a_bad_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={})

    with pytest.raises(ModelUnavailable):
        model(handler).complete(REQUEST)


def test_a_timeout_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(ModelUnavailable):
        model(handler).complete(REQUEST)


def test_a_rejected_credential_is_raised_rather_than_retried() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(401, json={})

    with pytest.raises(Exception) as error:
        model(handler).complete(REQUEST)

    assert len(attempts) == 1
    assert not isinstance(error.value, ModelUnavailable)


def test_a_response_with_no_choices_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(ModelUnavailable):
        model(handler).complete(REQUEST)


def test_missing_usage_is_reported_as_absent_rather_than_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    response = model(handler).complete(REQUEST)

    assert response.usage.prompt_tokens is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_openrouter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.ai.openrouter'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/ai/openrouter.py`:

```python
"""OpenRouter chat completions, the only file in `ai/` that opens a socket.

One adapter serves the whole ladder: a tier is a model id and a price, not a
protocol. Retries cover the statuses a free endpoint returns when it is busy;
everything else is raised, because retrying a rejected credential only spends
the run's request budget on a problem that will not fix itself.
"""

import time
from collections.abc import Callable
from time import sleep as default_sleep
from typing import Any

import httpx

from episignal_backend.ai.documents import ChatRequest, ChatResponse, TokenUsage
from episignal_backend.ai.protocol import ModelUnavailable

BASE_URL = "https://openrouter.ai/api/v1"
TIMEOUT_SECONDS = 60.0
MAX_ATTEMPTS = 3
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
RETRY_DELAY_SECONDS = 2.0


class CredentialRejected(Exception):
    """The key was refused. Nothing about this run will improve by asking again."""


class OpenRouterChatModel:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = default_sleep,
        timeout_seconds: float = TIMEOUT_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._sleep = sleep
        self._max_attempts = max_attempts

    def complete(self, request: ChatRequest) -> ChatResponse:
        payload = {
            "model": request.model_id,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "response_format": {"type": "json_object"},
        }
        started = time.monotonic()
        response = self._post(payload)
        latency_ms = int((time.monotonic() - started) * 1000)

        return ChatResponse(
            content=_content(response),
            usage=_usage(response),
            http_status=200,
            latency_ms=latency_ms,
        )

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        last = ""
        for attempt in range(self._max_attempts):
            try:
                response = self._client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as error:
                last = type(error).__name__
            else:
                if response.status_code in {401, 403}:
                    raise CredentialRejected(f"OpenRouter refused the key ({response.status_code})")
                if response.status_code not in RETRY_STATUS:
                    response.raise_for_status()
                    body: dict[str, Any] = response.json()
                    return body
                last = str(response.status_code)

            if attempt + 1 < self._max_attempts:
                self._sleep(RETRY_DELAY_SECONDS)

        raise ModelUnavailable(last)


def _content(body: dict[str, Any]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelUnavailable("no choices in the response")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ModelUnavailable("no message content in the response")
    return content


def _usage(body: dict[str, Any]) -> TokenUsage:
    # Absent rather than zero: a ledger that records a call as free when the
    # provider simply did not say is a ledger that understates the truth.
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return TokenUsage()
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    return TokenUsage(
        prompt_tokens=prompt if isinstance(prompt, int) else None,
        completion_tokens=completion if isinstance(completion, int) else None,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_openrouter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/openrouter.py packages/backend/tests/test_openrouter.py
git commit -m "feat: add the OpenRouter adapter with bounded retries"
```

---
## Task 19: Configuration

**Files:**
- Modify: `packages/backend/src/episignal_backend/config.py`
- Test: `packages/backend/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `packages/backend/tests/test_config.py`, following the environment
handling the existing tests in that module already use:

```python
def test_the_ai_defaults_describe_a_free_ladder() -> None:
    settings = build_settings()

    assert settings.ai_max_tier == 3
    assert settings.ai_batch_size == 20
    assert settings.ai_max_requests_per_run == 200
    assert settings.ai_min_confidence == 0.60


def test_the_openrouter_key_is_absent_by_default() -> None:
    settings = build_settings()

    assert settings.openrouter_api_key is None


def test_the_openrouter_key_is_not_printed_by_repr() -> None:
    settings = build_settings(EPISIGNAL_OPENROUTER_API_KEY="sk-secret-value")

    assert "sk-secret-value" not in repr(settings)


def test_a_batch_larger_than_the_run_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_settings(
            EPISIGNAL_AI_BATCH_SIZE="500", EPISIGNAL_AI_SIGNAL_BATCH_LIMIT="100"
        )


def test_a_confidence_floor_outside_zero_to_one_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_AI_MIN_CONFIDENCE="1.5")


def test_a_zero_request_cap_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_AI_MAX_REQUESTS_PER_RUN="0")


def test_a_negative_cost_cap_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_AI_MAX_COST_USD_PER_RUN="-1")


def test_a_tier_above_the_ladder_is_rejected() -> None:
    with pytest.raises(ValidationError):
        build_settings(EPISIGNAL_AI_MAX_TIER="4")
```

`build_settings` is whatever helper that module already uses to construct
`Settings` with a valid database URL and overridden environment; reuse it rather
than adding another.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_config.py -k "ai_ or openrouter" -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'ai_max_tier'`

- [ ] **Step 3: Write minimal implementation**

In `packages/backend/src/episignal_backend/config.py`, add after the `stage0_*`
block:

```python
    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    ai_signal_batch_limit: int = Field(default=100, ge=1, le=5000)
    ai_batch_size: int = Field(default=20, ge=1, le=200)
    # The binding guard under a free ladder: free endpoints are rated per
    # request and per day, so a run that respects a dollar cap can still burn a
    # day's quota in a minute.
    ai_max_requests_per_run: int = Field(default=200, ge=1, le=10000)
    ai_max_cost_usd_per_run: Decimal = Field(default=Decimal("0.50"), ge=0)
    ai_min_confidence: float = Field(default=0.60, ge=0.0, le=1.0)
    ai_max_input_characters: int = Field(default=12000, ge=500, le=200000)
    ai_request_delay_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    ai_request_timeout_seconds: float = Field(default=60.0, ge=1.0, le=300.0)
    ai_max_attempts_per_tier: int = Field(default=3, ge=1, le=10)
    ai_max_tier: int = Field(default=3, ge=1, le=3)
```

and a validator beside the existing `window_covers_the_interval`:

```python
    @model_validator(mode="after")
    def batch_fits_the_run(self) -> "Settings":
        # A batch larger than the run's queue would make the guards unreadable:
        # the run would appear to stop early when it had simply asked for more
        # signals than it selected.
        if self.ai_batch_size > self.ai_signal_batch_limit:
            raise ValueError(
                "EPISIGNAL_AI_BATCH_SIZE must not exceed EPISIGNAL_AI_SIGNAL_BATCH_LIMIT"
            )
        return self
```

Add `from decimal import Decimal` to the imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/config.py packages/backend/tests/test_config.py
git commit -m "feat: add the AI ladder and guard configuration"
```

---

## Task 20: The command

**Files:**
- Create: `packages/backend/src/episignal_backend/extract_runner.py`
- Modify: `package.json`
- Test: `packages/backend/tests/test_extract_runner.py`

Follow `packages/backend/src/episignal_backend/dedupe_runner.py`: argument
parsing separated from the run, counts on stdout, and a bare failure message on
stderr that names nothing sensitive.

- [ ] **Step 1: Write the failing test**

Create `packages/backend/tests/test_extract_runner.py`:

```python
import pytest

from episignal_backend.extract_runner import Arguments, main, parse_arguments


def test_defaults_run_both_stages() -> None:
    assert parse_arguments([]) == Arguments(limit=None, batch_size=None, stage="both")


def test_a_single_stage_can_be_selected() -> None:
    assert parse_arguments(["--stage", "classify"]).stage == "classify"


def test_an_unknown_stage_is_refused() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["--stage", "guess"])


def test_the_pnpm_double_dash_separator_is_ignored() -> None:
    assert parse_arguments(["--", "--limit", "5"]).limit == 5


def test_a_successful_run_prints_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "episignal_backend.extract_runner._run",
        lambda arguments: (
            _classification_result(), _extraction_result()
        ),
    )

    assert main([]) == 0

    output = capsys.readouterr().out
    assert "classified=" in output
    assert "extracted=" in output


def test_a_missing_api_key_stops_the_run_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(arguments: Arguments) -> None:
        raise RuntimeError("EPISIGNAL_OPENROUTER_API_KEY is not set")

    monkeypatch.setattr("episignal_backend.extract_runner._run", explode)

    assert main([]) == 1
    assert "OPENROUTER" in capsys.readouterr().err


def test_a_failing_run_never_prints_a_body_or_a_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(arguments: Arguments) -> None:
        raise RuntimeError("sk-secret-value leaked into an exception")

    monkeypatch.setattr("episignal_backend.extract_runner._run", explode)

    assert main([]) == 1
    captured = capsys.readouterr()
    assert "sk-secret-value" not in captured.err
    assert "sk-secret-value" not in captured.out
```

Define `_classification_result` and `_extraction_result` in the test module as
small helpers returning the two result dataclasses with fixed counts.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/backend/tests/test_extract_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'episignal_backend.extract_runner'`

- [ ] **Step 3: Write minimal implementation**

Create `packages/backend/src/episignal_backend/extract_runner.py`:

```python
"""Entry point for `pnpm extract:signals`.

Counts only. The API key, the prompts, and the article bodies never reach
stdout or stderr, the same posture as `discover_runner.py` and
`dedupe_runner.py`. A failure message says what stage failed and nothing about
what was in it.

Re-running is safe: each pass selects only signals still awaiting its decision,
so a second run in the same minute does nothing.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from episignal_backend.ai.classify import ClassificationResult, run_classification
from episignal_backend.ai.extract import ExtractionResult, run_extraction
from episignal_backend.ai.ladder import Guards
from episignal_backend.ai.openrouter import OpenRouterChatModel
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope

Stage = Literal["classify", "extract", "both"]


@dataclass(frozen=True)
class Arguments:
    limit: int | None
    batch_size: int | None
    stage: Stage


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="extract",
        description="Classify normalized signals and extract epidemiological facts.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Signals to examine per pass. Defaults to EPISIGNAL_AI_SIGNAL_BATCH_LIMIT.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Signals per classification request. Defaults to EPISIGNAL_AI_BATCH_SIZE.",
    )
    parser.add_argument(
        "--stage",
        choices=("classify", "extract", "both"),
        default="both",
        help="Which pass to run.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(limit=parsed.limit, batch_size=parsed.batch_size, stage=parsed.stage)


def _run(arguments: Arguments) -> tuple[ClassificationResult, ExtractionResult]:
    settings = get_settings()
    if settings.openrouter_api_key is None:
        raise RuntimeError("EPISIGNAL_OPENROUTER_API_KEY is not set")

    model = OpenRouterChatModel(
        settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        timeout_seconds=settings.ai_request_timeout_seconds,
        max_attempts=settings.ai_max_attempts_per_tier,
    )
    guards = Guards(
        max_requests=settings.ai_max_requests_per_run,
        max_cost_usd=settings.ai_max_cost_usd_per_run,
    )
    limit = arguments.limit or settings.ai_signal_batch_limit
    batch_size = arguments.batch_size or settings.ai_batch_size

    classified = ClassificationResult()
    extracted = ExtractionResult()

    with session_scope() as session:
        repository = SqlAlchemyAiRepository(session)
        if arguments.stage in {"classify", "both"}:
            classified = run_classification(
                repository,
                model,
                guards=guards,
                batch_size=batch_size,
                limit=limit,
                max_tier=settings.ai_max_tier,
                max_input_characters=settings.ai_max_input_characters,
            )
        if arguments.stage in {"extract", "both"}:
            extracted = run_extraction(
                repository,
                model,
                guards=guards,
                limit=limit,
                max_tier=settings.ai_max_tier,
                max_input_characters=settings.ai_max_input_characters,
                min_confidence=settings.ai_min_confidence,
            )

    return classified, extracted


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        classified, extracted = _run(arguments)
    except Exception as error:
        # The message is fixed text plus the exception's type, never its
        # payload: an exception raised near a prompt can carry the article, and
        # one raised near the client can carry the key.
        print(
            f"Extraction failed before completing ({type(error).__name__}). "
            "Check the database and EPISIGNAL_OPENROUTER_API_KEY.",
            file=sys.stderr,
        )
        return 1

    print(
        f"classified={classified.examined} relevant={classified.relevant} "
        f"irrelevant={classified.irrelevant} extracted={extracted.extracted} "
        f"review={classified.reviewed + extracted.reviewed} "
        f"unavailable={classified.unavailable + extracted.unavailable} "
        f"requests={classified.requests + extracted.requests} "
        f"stopped_early={classified.stopped_early or extracted.stopped_early}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The test for a leaked key passes because the message never interpolates the
exception's text. Keep it that way.

In `package.json`, add beside `dedupe:signals`:

```json
    "extract:signals": "uv run --package episignal-backend python -m episignal_backend.extract_runner",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/backend/tests/test_extract_runner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/extract_runner.py packages/backend/tests/test_extract_runner.py package.json
git commit -m "feat: add the extract command and its configuration"
```

---

## Task 21: Live verification and the quality gates

Nothing above this line has spoken to OpenRouter or to Postgres. This task does
both, once, and records what it saw.

- [ ] **Step 1: Confirm the seeded model ids still exist**

The roster was written from the free endpoints available on this plan's date.
Free endpoints are withdrawn without notice, so confirm all three before
trusting a run:

```bash
curl -s https://openrouter.ai/api/v1/models | grep -o '"id":"[^"]*:free"' | sort
```

Every `model_id` in `database/seeds/ai_models.json` must appear. Replace any that
does not, keeping one vendor per tier, and re-run `corepack pnpm db:seed`. Record
what was changed in the report.

- [ ] **Step 2: Migrate and seed**

```bash
corepack pnpm db:migrate
```

```bash
corepack pnpm db:seed
```

Confirm `ai_models` holds three active rows and that `signals.disease_id` exists.

- [ ] **Step 3: Prove the rollback refuses to discard the ledger**

With `ai_requests` empty, `corepack pnpm db:rollback` must succeed and
`corepack pnpm db:migrate` must restore the tables. Then insert one cost row by
hand, attempt the rollback again, and confirm it raises and names
`EPISIGNAL_ALLOW_AI_AUDIT_LOSS`. Delete the hand-written row afterwards.

- [ ] **Step 4: Run one live pass**

With `EPISIGNAL_OPENROUTER_API_KEY` set and at least one `normalized` signal in
the database:

```bash
corepack pnpm extract:signals -- --limit 5 --batch-size 5
```

Confirm, by reading the database:

- every signal that was `normalized` is now `classified`, `extracted`,
  `needs_review`, or unchanged, and none is `duplicate` or `fetched`;
- `ai_requests` holds one row per request, with non-null `latency_ms` and a
  `cost_usd` of `0.000000` on every free row;
- every `ai_extraction` that stores a count also stores a `source_span` that
  appears in that signal's `raw_text`.

The third check is the acceptance of the whole sub-project. Verify it by reading
one extraction and one article side by side, not by trusting the pass that wrote
it.

- [ ] **Step 5: Run the full gate**

```bash
uv run pytest
```

```bash
uv run ruff check .
```

```bash
uv run ruff format --check .
```

```bash
uv run mypy apps/api/src packages/backend/src
```

```bash
corepack pnpm verify
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: verify AI classification, extraction, and cost logging end to end"
```

---

## Acceptance criteria

The sub-project is done when every one of these holds. They restate the design's
acceptance criteria as things a reader can check.

1. `uv run pytest` passes, with no test opening a socket, reading a credential,
   or connecting to a database.
2. `ruff check`, `ruff format --check`, and `mypy` are clean, and
   `corepack pnpm verify` passes.
3. A `normalized` signal about an outbreak ends `extracted`, with
   `ai_extraction`, `ai_model`, `ai_processed_at`, and `disease_id` set when the
   disease is one the vocabulary knows.
4. A `normalized` signal about anything else ends `classified` with
   `public_health_relevant` false, and no extraction request is made for it.
5. `duplicate`, `needs_review`, and `fetched` signals are never selected by
   either pass, proven by a test that reads the compiled selection query.
6. An answer whose `source_span` is not in the article is rejected, escalates,
   and never reaches the database.
7. A classification answer whose id set differs from the batch sent is rejected
   whole.
8. A grounded answer about a French-language article is accepted at tier one in
   exactly one request.
9. Every request writes an `ai_requests` row, including rejected and unavailable
   ones, carrying tokens, latency, outcome, the price in force, and a computed
   cost.
10. An unreachable provider leaves signals exactly as they were, and the next run
    selects them again.
11. A run that reaches its request cap stops, reports `stopped_early`, and leaves
    the rest for the next run.
12. `pnpm db:rollback` over 0005 refuses while `ai_requests` holds rows unless
    `EPISIGNAL_ALLOW_AI_AUDIT_LOSS=1`.
13. No module in `ai/` imports SQLAlchemy except `repository.py`, and none
    imports httpx except `openrouter.py`.
14. Nothing in this slice writes `verification_status`, an `events` row, or a new
    `diseases` row.

## Known follow-on work, deliberately not in this plan

- Geocoding extracted place names, and the location roles that go with them.
- Clustering, event matching, and the two scores, all sub-project D.
- An admin view over `ai_requests` and over signals in `needs_review`, which is
  sub-project E's surface.
- The benchmarking harness that decides which free model deserves tier one,
  which is sub-project F and is the reason the ledger records rejected and
  unavailable requests as well as accepted ones.
- A paid rung. The roster, the prices, and the cost guard already support one;
  adding it is a seed row and a key, not a code change.

## Primary references

- `docs/superpowers/specs/2026-08-27-ai-extraction-design.md` — the design this
  plan implements.
- `docs/superpowers/specs/2026-08-27-gdelt-layer-architecture.md` — the
  invariants no task may relax.
- `HANDOFF.md` — the four invariants for this sub-project, and the Windows
  command forms.
- `CONTEXT.md` — the naming authority for tier, escalation, source span,
  grounding, cost row, unavailable, and verdict.
- `AGENTS.md` — model routing, TDD rules, and the review and verification gates
  that close this work.
