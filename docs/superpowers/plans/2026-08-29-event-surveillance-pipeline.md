# Event-Based Surveillance Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task by
> task. Steps use checkbox (`- [ ]`) syntax for tracking. Project skills
> `lean-build`, `tdd`, and `migration` apply throughout, per `AGENTS.md`.

**Date:** 2026-08-29
**Spec:** [2026-08-29-event-surveillance-pipeline-design.md](../specs/2026-08-29-event-surveillance-pipeline-design.md)
**Roadmap item:** `R` — depends on `O2`. Absorbs the embedding half of `D2b`.

**Goal:** Give the funnel the article's own disease and geography early enough
to block candidates on, match events semantically without ever overriding a
deterministic conflict, and give each event one narrative summary that is
traceable to the articles that produced it.

**Architecture:** Three phases, each independently shippable and separately
verified. Phase A adds a structured triage pass after retrieval. Phase B adds
pgvector and BGE-M3 embeddings, consulted only for pairs the existing
deterministic guards already permit. Phase C fills the dead `events.ai_summary`
column from a DeepSeek pass that runs only on a material update and records its
evidence.

**Tech stack:** Python 3.12, SQLAlchemy 2, Alembic, Pydantic v2, pgvector,
sentence-transformers (BGE-M3), pytest, mypy strict, ruff. `uv` for Python,
`corepack pnpm` for the workspace.

**Branch:** create `codex/event-surveillance` in a separate worktree from
`main`. `O2` was merged to `main` at `5590444` on 2026-08-30; its live-proof
run and completion report were waived by operator decision, so there is no `O2`
report to read. This plan is written against the post-`O2` code
shape: `retrieve` and `pregroup` are chain stages, `filtered` is a status, and
cluster extraction runs inside `run_extraction`.

**Worker contract:** test-first per task; tick the task in `STATUS.md` in the
same commit that completes it; run the scoped tests before committing. Stop at
each phase checkpoint and report before continuing. Stop after Task 26 and hand
back to the planner. Do **not** mark the roadmap item `verified`.

---

## File structure

**Created**

| File | Responsibility |
| --- | --- |
| `ingestion/normalize_title.py` | Pure title normalization for pre-fetch dedup. |
| `ai/triage.py` | The Llama structured triage pass. |
| `ai/embeddings.py` | `EmbeddingProvider` Protocol and the local BGE-M3 provider. |
| `events/summarize.py` | Material-update detection, representative selection, the DeepSeek pass. |
| `events/summary_schema.py` | The event summary contract and its validator. |
| `triage_runner.py`, `embed_runner.py`, `summarize_runner.py` | Manual entry points. |
| `database/migrations/versions/20260830_0017_triage_metadata.py` | `normalized_title`, triage columns, `ai_models.purpose`. |
| `database/migrations/versions/20260830_0018_pgvector_embeddings.py` | pgvector extension, `signals.embedding`, HNSW index. |
| `database/migrations/versions/20260830_0019_event_summaries.py` | `event_summary_history`, `ai_requests.event_id`. |
| `packages/backend/tests/fixtures/calibration/` | The four event-matching scenarios. |
| `docs/news-event-pipeline.md` | The operator-facing document the brief asks for. |

**Modified**

| File | Change |
| --- | --- |
| `db/types.py` | `AiPurpose.TRIAGE`, `AiPurpose.EVENT_SUMMARY`, `TriageStatus`. |
| `models/signal.py` | `normalized_title`, triage columns, `embedding`. |
| `models/ai.py` | `AiModel.purpose`, `AiRequest.event_id`. |
| `models/event.py` | `EventSummaryHistory`. |
| `ai/ladder.py` | `Ladder.build(..., purpose=)`. |
| `ai/repository.py` | Triage, embedding, and summary selections. |
| `ai/spend.py`, `spend_runner.py` | The five aggregates the brief asks for. |
| `events/cluster.py`, `match.py`, `assemble.py` | Similarity as an additive term; typed rejection reasons. |
| `events/repository.py` | Candidate blocking by lookback and limit; summary storage. |
| `ingestion/retrieval.py` | Normalized-title dedup before the fetch. |
| `schedule/documents.py`, `chains.py`, `stages.py` | `TRIAGE`, `EMBED`, `SUMMARIZE` stages. |
| `config.py` | Every threshold in the spec. |
| `apps/api/.env.example` | The new variables. |
| `database/seeds/ai_models.json` | Llama and DeepSeek rows. |
| `pyproject.toml` | `pgvector`, `sentence-transformers`. |

---

## Before Task 1

- [ ] **Create the worktree and a clean baseline**

```bash
git worktree add ../EpiSignal-event-surveillance -b codex/event-surveillance main
```

Copy `apps/api/.env` into the new worktree — it is gitignored and nothing runs
without it. `apps/api/.env.example` documents the names. Then:

```bash
corepack pnpm install && corepack pnpm verify
```

Expected: exit code 0. Record the commit and test counts. If red, stop and
report.

---

# Phase A — Early structured metadata

## Task 1: Normalized title

**Files:**
- Create: `packages/backend/src/episignal_backend/ingestion/normalize_title.py`
- Test: `packages/backend/tests/test_normalize_title.py`

- [ ] **Step 1: Write the failing test**

```python
from episignal_backend.ingestion.normalize_title import normalize_title


def test_case_and_whitespace_are_collapsed() -> None:
    assert normalize_title("  Dengue   Outbreak\nIn Chiang Mai ") == "dengue outbreak in chiang mai"


def test_a_publisher_suffix_is_dropped() -> None:
    assert normalize_title("Dengue outbreak in Chiang Mai - Bangkok Post") == "dengue outbreak in chiang mai"
    assert normalize_title("Dengue outbreak in Chiang Mai | Reuters") == "dengue outbreak in chiang mai"


def test_a_hyphenated_phrase_is_not_mistaken_for_a_suffix() -> None:
    # Only a suffix after the LAST separator, and only when what follows is
    # short enough to be a masthead rather than part of the headline.
    assert normalize_title("Mother-to-child transmission confirmed") == "mother-to-child transmission confirmed"


def test_punctuation_and_unicode_are_folded() -> None:
    assert normalize_title("Dengue “outbreak” in Chiang Mai!") == "dengue outbreak in chiang mai"
    assert normalize_title("DENGUE OUTBREAK") == "dengue outbreak"


def test_two_genuinely_different_headlines_do_not_collapse() -> None:
    first = normalize_title("Dengue outbreak in Chiang Mai")
    second = normalize_title("Dengue outbreak in Phuket")

    assert first != second


def test_a_blank_title_normalizes_to_empty() -> None:
    assert normalize_title("   ") == ""
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest packages/backend/tests/test_normalize_title.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the module**

```python
"""One headline, reduced to the form two syndicated copies share.

Deliberately conservative. This value is compared for equality before a page is
fetched, so a rule that folds two genuinely different headlines together costs
a real article. Everything here removes presentation -- case, spacing,
punctuation, the masthead a wire service appends -- and nothing removes words.

This module imports neither SQLAlchemy nor httpx.
"""

import re
import unicodedata

# A masthead, not part of the headline: short, and after the last separator.
_SUFFIX = re.compile(r"\s[-|–—]\s([^-|–—]{1,40})$")
_PUNCTUATION = re.compile(r"[^\w\s-]", flags=re.UNICODE)


def normalize_title(title: str) -> str:
    # NFKC folds the non-breaking spaces and typographic quotes publishers emit
    # into the plain characters two copies of one story will agree on.
    folded = unicodedata.normalize("NFKC", title)
    without_suffix = _SUFFIX.sub("", folded)
    stripped = _PUNCTUATION.sub("", without_suffix)
    return " ".join(stripped.split()).casefold()
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest packages/backend/tests/test_normalize_title.py -v
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(ingest): normalize a headline for pre-fetch comparison"
```

---

## Task 2: Triage vocabulary and schema columns

**Files:**
- Modify: `db/types.py`, `models/signal.py`, `models/ai.py`
- Create: `database/migrations/versions/20260830_0017_triage_metadata.py`
- Modify: `apps/api/tests/test_migrations.py`
- Test: `packages/backend/tests/test_models.py`, `apps/api/tests/test_migrations.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_triage_and_summary_are_costed_purposes() -> None:
    assert AiPurpose.TRIAGE == "triage"
    assert AiPurpose.EVENT_SUMMARY == "event_summary"


def test_a_roster_row_may_name_the_purpose_it_serves() -> None:
    assert AiModel.purpose.nullable is True


def test_the_migration_widens_the_purpose_constraint() -> None:
    sql = render_offline("upgrade", "20260829_0017:20260830_0017")
    assert "'triage'" in sql
    assert "'event_summary'" in sql
    assert "normalized_title" in sql
```

Update the head assertion to `["20260830_0017"]`.

- [ ] **Step 2: Run them to confirm they fail**

```bash
uv run pytest apps/api/tests/test_migrations.py packages/backend/tests/test_models.py -v
```

- [ ] **Step 3: Extend the vocabularies**

In `db/types.py`:

```python
class AiPurpose(StrEnum):
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    FOLLOW_UP = "follow_up"
    # Title-and-snippet structured triage: relevance plus the disease and place
    # that candidate blocking needs before extraction has run.
    TRIAGE = "triage"
    # One narrative per event, regenerated only on a material update.
    EVENT_SUMMARY = "event_summary"


class TriageStatus(StrEnum):
    """How far triage got with one signal. Failure is a state, not a silence."""

    PENDING = "pending"
    DONE = "done"
    # The model answered twice and neither answer validated. The signal stays
    # selectable; the ledger says why.
    FAILED = "failed"
```

In `models/signal.py`, add:

```python
    normalized_title: Mapped[str | None] = mapped_column(Text)
    triage_status: Mapped[TriageStatus] = mapped_column(
        vocabulary(TriageStatus, "triage_status_values"),
        nullable=False,
        default=TriageStatus.PENDING,
        server_default=TriageStatus.PENDING.value,
    )
    triage_category: Mapped[str | None] = mapped_column(Text)
    triage_disease_text: Mapped[str | None] = mapped_column(Text)
    triage_country_code: Mapped[str | None] = mapped_column(String(2))
    triage_admin1: Mapped[str | None] = mapped_column(Text)
    triage_admin2: Mapped[str | None] = mapped_column(Text)
    triage_location_text: Mapped[str | None] = mapped_column(Text)
    triage_confidence: Mapped[float | None] = mapped_column(Float)
```

with `Index("ix_signals_normalized_title", "normalized_title")` and
`Index("ix_signals_triage_block", "triage_disease_text", "triage_country_code")`
added to `__table_args__`.

In `models/ai.py`, add `purpose` to `AiModel` (nullable, the same `vocabulary`
type as the cost row's) and `event_id` is deferred to Task 20.

- [ ] **Step 4: Write the migration**

`20260830_0017_triage_metadata.py`, revises `20260829_0017`. It must:

1. widen the `ai_purpose` CHECK constraint on `ai_requests` with `triage` and
   `event_summary`, using the drop-and-recreate pattern of
   `20260829_0016_filtered_status.py` — these are CHECK constraints, not pg
   enums;
2. add the nine `signals` columns above, all nullable except `triage_status`
   which takes a server default so existing rows are `pending`;
3. add `ai_models.purpose`, nullable, with its own CHECK constraint;
4. create the two indexes;
5. backfill `normalized_title` for existing rows with a SQL expression
   equivalent to the Python function — `lower(regexp_replace(...))` — and note
   in the docstring that the authority is the Python function and the backfill
   is a convenience, re-derivable by re-running triage;
6. downgrade drops the columns and indexes and narrows both constraints.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest apps/api/tests/test_migrations.py packages/backend/tests/test_models.py packages/backend/tests/test_schema_check.py -v
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat(schema): add triage metadata and purpose-scoped rosters"
```

---

## Task 3: Purpose-scoped ladder

**Files:**
- Modify: `ai/ladder.py`, `ai/documents.py` (`ModelSpec.purpose`), `ai/repository.py` (`models()`)
- Modify: `database/seeds/ai_models.json`, `seeds.py` (`AiModelSeed.purpose`)
- Test: `packages/backend/tests/test_ai_ladder.py`, `test_seeds.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_purposeless_rung_serves_every_purpose() -> None:
    ladder = Ladder.build((GEMINI_ANY,), max_tier=3, purpose=AiPurpose.EXTRACTION)

    assert ladder.rungs == (GEMINI_ANY,)


def test_a_purposed_rung_is_hidden_from_other_purposes() -> None:
    with pytest.raises(NoModelsConfigured):
        Ladder.build((LLAMA_TRIAGE,), max_tier=3, purpose=AiPurpose.EXTRACTION)


def test_a_purposed_rung_serves_its_own_purpose() -> None:
    ladder = Ladder.build(
        (GEMINI_ANY, LLAMA_TRIAGE), max_tier=3, purpose=AiPurpose.TRIAGE
    )

    assert LLAMA_TRIAGE in ladder.rungs


def test_the_seed_carries_a_triage_and_a_summary_model() -> None:
    models = {seed.model_id: seed for seed in load_ai_models()}

    assert models["meta-llama/llama-3.1-8b-instruct"].purpose is AiPurpose.TRIAGE
    assert models["deepseek/deepseek-v4-flash-0731"].purpose is AiPurpose.EVENT_SUMMARY


def test_every_existing_rung_stays_purposeless() -> None:
    # A purpose on an existing row would change which pass can use it.
    for seed in load_ai_models():
        if seed.model_id.startswith(("google/", "mistralai/", "anthropic/")):
            assert seed.purpose is None
```

- [ ] **Step 2: Run them to confirm they fail**

```bash
uv run pytest packages/backend/tests/test_ai_ladder.py packages/backend/tests/test_seeds.py -v
```

- [ ] **Step 3: Add the purpose to the spec, the seed, and the ladder**

`ModelSpec` and `AiModelSeed` each gain `purpose: AiPurpose | None = None`.
`SqlAlchemyAiRepository.models()` passes `purpose=row.purpose` through.

In `ai/ladder.py`:

```python
    @classmethod
    def build(
        cls,
        specs: Sequence[ModelSpec],
        *,
        max_tier: int,
        min_tier: int = 1,
        purpose: AiPurpose | None = None,
    ) -> "Ladder":
        """Rungs for one purpose, tier-sorted.

        A rung with no purpose serves every pass, which is what every rung did
        before purposes existed. A rung that names a purpose is invisible to
        every other pass, so an 8B triage model can never answer an extraction.
        """
        eligible = [
            spec
            for spec in specs
            if spec.purpose is None or spec.purpose is purpose
        ]
        within_max = (spec for spec in eligible if spec.tier <= max_tier)
        ...
```

The rest of `build` is unchanged, operating on `eligible`.

Append to `database/seeds/ai_models.json`:

```json
  {
    "tier": 1,
    "model_id": "meta-llama/llama-3.1-8b-instruct",
    "label": "Llama 3.1 8B Instruct",
    "provider": "openrouter",
    "purpose": "triage",
    "prompt_price_per_million": "0.02",
    "completion_price_per_million": "0.03",
    "active": true
  },
  {
    "tier": 1,
    "model_id": "deepseek/deepseek-v4-flash-0731",
    "label": "DeepSeek V4 Flash",
    "provider": "openrouter",
    "purpose": "event_summary",
    "prompt_price_per_million": "0.10",
    "completion_price_per_million": "0.30",
    "active": true
  }
```

Verify both prices against OpenRouter's current listing before committing and
correct them if they have moved; a wrong price makes every cost row wrong.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest packages/backend/tests/test_ai_ladder.py packages/backend/tests/test_seeds.py packages/backend/tests/test_ai_repository.py -v
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(ai): scope roster rungs to the purpose they serve"
```

---

## Task 4: The triage contract

**Files:**
- Create the schema in `ai/schema.py` (alongside the extraction contract)
- Test: `packages/backend/tests/test_ai_schema.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_triage_verdict_allows_every_fact_to_be_missing() -> None:
    verdict = TriageVerdict.model_validate(
        {"relevant": True, "public_health": True, "confidence": 0.9}
    )

    assert verdict.disease is None
    assert verdict.country is None
    assert verdict.admin1 is None


def test_a_two_letter_country_is_required_when_present() -> None:
    with pytest.raises(ValidationError):
        TriageVerdict.model_validate(
            {"relevant": True, "public_health": True, "confidence": 0.9, "country": "Thailand"}
        )


def test_an_empty_string_is_read_as_missing() -> None:
    # An 8B model writes "" where it means null more often than it writes null.
    verdict = TriageVerdict.model_validate(
        {"relevant": True, "public_health": True, "confidence": 0.9, "admin1": "  "}
    )

    assert verdict.admin1 is None


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ValidationError):
        TriageVerdict.model_validate(
            {"relevant": True, "public_health": True, "confidence": 0.9, "severity": "high"}
        )
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest packages/backend/tests/test_ai_schema.py -v
```

- [ ] **Step 3: Write the contract**

In `ai/schema.py`:

```python
class TriageCategory(StrEnum):
    INFECTIOUS_DISEASE = "infectious_disease"
    ENVIRONMENTAL = "environmental"
    CHEMICAL = "chemical"
    OTHER_PUBLIC_HEALTH = "other_public_health"
    NOT_PUBLIC_HEALTH = "not_public_health"


class TriageVerdict(BaseModel):
    """What a cheap model can say from a headline and an opening paragraph.

    Every fact is nullable because a headline routinely carries none of them,
    and a model that must fill a field will invent one. Only the two booleans
    and the confidence are required, because those are judgements rather than
    facts and the model always has one.
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
        # A small model writes "" and "unknown" where it means null.
        if isinstance(value, str) and (not value.strip() or value.strip().lower() in {"unknown", "n/a", "none"}):
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
```

- [ ] **Step 4: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_ai_schema.py -v
git add -A && git commit -m "feat(ai): define the triage contract"
```

---

## Task 5: The triage prompt

**Files:**
- Modify: `ai/prompts.py`
- Test: `packages/backend/tests/test_ai_prompts.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_triage_prompt_carries_the_metadata_a_blocking_key_needs() -> None:
    system, user = triage_prompt(SIGNAL, max_characters=1200)

    assert "null" in system
    assert "TITLE:" in user
    assert "SOURCE:" in user
    assert "PUBLISHED:" in user
    assert "URL:" in user


def test_the_triage_prompt_truncates_the_snippet() -> None:
    _, user = triage_prompt(LONG_SIGNAL, max_characters=100)

    assert LONG_SIGNAL.excerpt not in user


def test_a_repair_prompt_carries_the_validation_error() -> None:
    system, user = triage_repair_prompt(SIGNAL, error="country must be 2 characters", max_characters=1200)

    assert "country must be 2 characters" in user
    assert "TITLE:" in user
```

- [ ] **Step 2: Run it to confirm it fails, then write the prompt**

```python
TRIAGE_RULES = """You read one news item and return structured metadata as JSON.

Rules:
- Return one JSON object and nothing else. No prose, no code fence.
- Every field you are not certain of from the text you were given must be null.
  Never guess a disease, a country, or a province.
- country is a two-letter ISO 3166-1 alpha-2 code, or null.
- Judge relevance generously: when a headline might concern an outbreak, an
  unusual illness, or a public health response, mark it relevant. A missed
  outbreak costs more than a wasted look.
- Mark relevant false only when the item is plainly about something else --
  sport, business, entertainment, crime, politics with no health content.
- confidence is your confidence in relevant, not in the whole object.

The object must match this JSON Schema exactly:
"""

TRIAGE_REPAIR = """Your previous answer did not match the schema.

Error: {error}

Return the corrected JSON object and nothing else.
"""


def triage_prompt(signal: TriageableSignal, *, max_characters: int) -> tuple[str, str]:
    system = TRIAGE_RULES + json.dumps(triage_json_schema(), sort_keys=True)
    published = signal.published_at.isoformat() if signal.published_at else "unknown"
    user = (
        f"TITLE: {signal.title}\n"
        f"SOURCE: {signal.source_name}\n"
        f"PUBLISHED: {published}\n"
        f"URL: {signal.url}\n"
        f"LANGUAGE: {signal.language or 'unknown'}\n\n"
        f"SNIPPET:\n{truncate(signal.excerpt, max_characters)}"
    )
    return system, user


def triage_repair_prompt(
    signal: TriageableSignal, *, error: str, max_characters: int
) -> tuple[str, str]:
    """The one retry. Carries the failure so the model can see what it broke."""
    system, user = triage_prompt(signal, max_characters=max_characters)
    return system, user + "\n\n" + TRIAGE_REPAIR.format(error=error)
```

Add `TriageableSignal` to `ai/documents.py`: `id`, `title`, `excerpt`,
`source_name`, `url`, `published_at`, `language`.

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_ai_prompts.py -v
git add -A && git commit -m "feat(ai): build the triage prompt and its one repair"
```

---

## Task 6: The triage pass

**Files:**
- Create: `packages/backend/src/episignal_backend/ai/triage.py`
- Modify: `ai/protocol.py`, `ai/repository.py`
- Test: `packages/backend/tests/test_ai_triage.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_valid_answer_is_stored_and_costed() -> None:
    repository = TriageRepository(pending=(SIGNAL,))
    model = ScriptedModel([ChatResponse(content=GOOD_TRIAGE, latency_ms=10)])

    result = run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert result.triaged == 1
    assert result.repaired == 0
    assert repository.stored[SIGNAL.id].disease == "dengue"
    assert repository.requests[0].purpose is AiPurpose.TRIAGE


def test_a_malformed_answer_is_repaired_once() -> None:
    repository = TriageRepository(pending=(SIGNAL,))
    model = ScriptedModel([
        ChatResponse(content=MALFORMED, latency_ms=10),
        ChatResponse(content=GOOD_TRIAGE, latency_ms=10),
    ])

    result = run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert result.triaged == 1
    assert result.repaired == 1
    assert result.requests == 2


def test_two_bad_answers_fail_loudly_and_keep_the_signal() -> None:
    repository = TriageRepository(pending=(SIGNAL,))
    model = ScriptedModel([
        ChatResponse(content=MALFORMED, latency_ms=10),
        ChatResponse(content=MALFORMED, latency_ms=10),
    ])

    result = run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert result.failed == 1
    assert repository.statuses[SIGNAL.id] is TriageStatus.FAILED
    assert repository.deleted == []
    assert [r.outcome for r in repository.requests] == [AiOutcome.REJECTED, AiOutcome.REJECTED]


def test_it_never_repairs_more_than_once() -> None:
    repository = TriageRepository(pending=(SIGNAL,))
    model = ScriptedModel([ChatResponse(content=MALFORMED, latency_ms=10)] * 5)

    result = run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert result.requests == 2


def test_an_irrelevant_verdict_filters_the_signal() -> None:
    repository = TriageRepository(pending=(SIGNAL,))
    model = ScriptedModel([ChatResponse(content=IRRELEVANT_TRIAGE, latency_ms=10)])

    run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert repository.statuses[SIGNAL.id] is TriageStatus.DONE
    assert repository.filtered == [SIGNAL.id]


def test_a_known_disease_resolves_to_the_vocabulary() -> None:
    repository = TriageRepository(pending=(SIGNAL,), diseases={"dengue": DENGUE_ID})
    model = ScriptedModel([ChatResponse(content=GOOD_TRIAGE, latency_ms=10)])

    run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert repository.stored[SIGNAL.id].disease_id == DENGUE_ID


def test_an_unknown_disease_is_kept_as_text_and_resolves_to_nothing() -> None:
    repository = TriageRepository(pending=(SIGNAL,), diseases={})
    model = ScriptedModel([ChatResponse(content=GOOD_TRIAGE, latency_ms=10)])

    run_triage(repository, model, guards=guards(), now=lambda: NOW)

    assert repository.stored[SIGNAL.id].disease == "dengue"
    assert repository.stored[SIGNAL.id].disease_id is None


def test_the_budget_guard_stops_the_pass_cleanly() -> None:
    repository = TriageRepository(pending=(SIGNAL, SECOND))
    model = ScriptedModel([ChatResponse(content=GOOD_TRIAGE, latency_ms=10)])

    result = run_triage(
        repository, model, guards=Guards(max_requests=1, max_cost_usd=Decimal("1")), now=lambda: NOW
    )

    assert result.stopped_early is True
```

- [ ] **Step 2: Run it to confirm it fails**

```bash
uv run pytest packages/backend/tests/test_ai_triage.py -v
```

- [ ] **Step 3: Write the pass**

`ai/triage.py` mirrors `ai/classify.py`'s shape: build a ladder scoped to
`AiPurpose.TRIAGE`, batch through `repository.awaiting_triage(limit=...)`, climb
once per signal, and on `Rejected` retry exactly once with
`triage_repair_prompt`. Write a cost row for every attempt with
`purpose=AiPurpose.TRIAGE` and `batch_size=1`. Resolve `disease` through the
existing `repository.resolve_disease`, keeping the text either way. Store via
`repository.record_triage(signal_id, verdict, disease_id, at)`, which sets
`triage_status = DONE` and — when `relevant` is false — also sets
`processing_status = FILTERED`, the terminal status `O2` introduced.

`RunBudget` and `Guards` come from `ai/ladder.py` unchanged. A signal whose two
attempts both fail gets `triage_status = FAILED` and keeps its
`processing_status`, so it stays selectable for extraction rather than
disappearing.

Result dataclass: `examined`, `triaged`, `repaired`, `filtered`, `failed`,
`unavailable`, `requests`, `stopped_early`.

- [ ] **Step 4: Add the repository methods**

`awaiting_triage(limit)` selects `normalized` signals with
`triage_status = PENDING`, a body, and not deferred by an open group.
`record_triage(...)` writes the nine columns. Both go on the `AiRepository`
Protocol.

- [ ] **Step 5: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_ai_triage.py packages/backend/tests/test_ai_repository.py -v
git add -A && git commit -m "feat(ai): triage a signal into a blocking key"
```

---

## Task 7: Pre-fetch normalized-title dedup

**Files:**
- Modify: `ingestion/retrieval.py`, `ingestion/protocol.py`, `ingestion/repository.py`
- Test: `packages/backend/tests/test_retrieval.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_syndicated_copy_is_marked_duplicate_before_it_is_fetched() -> None:
    repository = FakeRetrievalRepository(
        waiting=(COPY,), rules=(OUTBREAK,), titles={COPY.normalized_title: ORIGINAL_ID}
    )
    connector = CountingConnector()

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)

    assert result.duplicates == 1
    assert connector.retrieved == 0
    assert repository.duplicated == [(COPY.signal_id, ORIGINAL_ID)]


def test_a_title_match_outside_the_window_is_still_fetched() -> None:
    # Two outbreaks a year apart can share a headline. Only a close pair is a
    # syndication candidate.
    repository = FakeRetrievalRepository(waiting=(COPY,), rules=(OUTBREAK,), titles={})
    connector = CountingConnector()

    result = run_retrieval(repository, connector, max_attempts=3, batch_size=10)

    assert result.duplicates == 0
    assert connector.retrieved == 1


def test_the_gate_runs_before_the_title_check() -> None:
    # A filtered article costs neither a fetch nor a title lookup.
    repository = FakeRetrievalRepository(waiting=(STADIUM,), rules=(OUTBREAK,), titles={})

    result = run_retrieval(repository, CountingConnector(), max_attempts=3, batch_size=10)

    assert result.filtered == 1
    assert repository.title_lookups == 0
```

- [ ] **Step 2: Run it, then implement**

`StubRetrieval` gains `normalized_title`. `DiscoveryRepository` gains
`title_duplicate_of(normalized_title: str, *, within_hours: int) -> UUID | None`,
which returns the earliest signal with that normalized title inside the window,
and `mark_title_duplicate(signal_id, primary_id)` reusing the existing
`DUPLICATE` status and `duplicate_of_signal_id` pointer.

In `run_retrieval`, between the gate decision and the fetch:

```python
        primary_id = repository.title_duplicate_of(
            item.normalized_title, within_hours=window_hours
        )
        if primary_id is not None:
            # Free: a syndicated copy is recognised from its headline, so the
            # publisher is never asked for a page this system already holds.
            repository.mark_title_duplicate(item.signal_id, primary_id)
            repository.commit()
            duplicates += 1
            continue
```

Add `duplicates` to `RetrievalResult` and to the stage summary. Window comes
from the existing `stage0_candidate_window_hours`.

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_retrieval.py packages/backend/tests/test_schedule_stages.py -v
git add -A && git commit -m "feat(retrieve): recognise a syndicated copy from its headline"
```

---

## Task 8: The `triage` stage and Phase A checkpoint

**Files:**
- Modify: `schedule/documents.py`, `chains.py`, `stages.py`, `config.py`
- Create: `triage_runner.py`; modify `package.json`, `apps/api/.env.example`
- Test: `packages/backend/tests/test_schedule_chains.py`, `test_triage_runner.py`

- [ ] **Step 1: Write the failing test**

```python
def test_triage_runs_after_dedupe_and_before_grouping() -> None:
    assert DAILY_CHAIN == (
        StageName.INGEST_WHO,
        StageName.INGEST_ECDC,
        StageName.DISCOVER,
        StageName.RETRIEVE,
        StageName.DEDUPE,
        StageName.TRIAGE,
        StageName.PREGROUP,
        StageName.EXTRACT,
        StageName.GEOCODE,
        StageName.MATCH,
    )
```

- [ ] **Step 2: Add the stage**

`StageName.TRIAGE = "triage"`, placed after `DEDUPE` — triage needs a body, so
it cannot precede retrieval, and grouping wants its blocking key, so it must
precede `PREGROUP`. `_triage()` in `stages.py` mirrors `_extract`'s wiring with
`purpose=AiPurpose.TRIAGE`. Add `ai_triage_batch_limit: int = 200` to settings
and `triage:signals` to `package.json`.

- [ ] **Step 3: Run the full suite**

```bash
uv run pytest -q
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat(schedule): run structured triage before grouping"
```

- [ ] **Step 5: PHASE A CHECKPOINT — stop and report**

Run `corepack pnpm verify` and report: test counts, the migration revision, and
a dry read of how many live signals now carry a `triage_disease_text` and a
`triage_country_code`. Do not start Phase B until the planner acknowledges.

---

# Phase B — Embeddings and semantic matching

## Task 9: pgvector and the embedding column

**Planner correction (2026-08-30):** The original task named three interfaces
that do not exist together in this tree. The operator-only live report in
`episignal_backend.schema_check` owns extension readiness; the public FastAPI
readiness contract remains the foundation's database/PostGIS contract. Add the
small `database_report(session)` interface to `schema_check.py`, have
`build_report()` merge its three component states, and make the command fail
when pgvector is unavailable. The signal-column constant is
`EXPECTED_SIGNAL_COLUMNS` (new), not the nonexistent `EXPECTED_COLUMNS`.
Python runtime dependencies belong to the backend member's pyproject, not the
dependency-empty workspace pyproject.

**Files:**
- Create: `database/migrations/versions/20260830_0018_pgvector_embeddings.py`
- Modify: `models/signal.py`, `packages/backend/pyproject.toml`, `schema_check.py`
- Test: `apps/api/tests/test_migrations.py`, `packages/backend/tests/test_schema_check.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_migration_enables_pgvector_and_indexes_the_embedding() -> None:
    sql = render_offline("upgrade", "20260830_0017:20260830_0018")

    assert "create extension if not exists vector" in sql
    assert "vector(1024)" in sql
    assert "hnsw" in sql


def test_the_health_check_reports_pgvector() -> None:
    # The fake session returns a version for the pg_extension vector probe and
    # a healthy connection for the existing database/PostGIS probe.
    report = database_report(session)

    assert report["pgvector"] == "up"
```

- [ ] **Step 2: Write the migration**

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("signals", sa.Column("embedding", Vector(1024), nullable=True))
    # HNSW rather than IVFFlat: the table grows continuously and IVFFlat needs
    # a rebuild to stay honest as it does.
    op.execute(
        "CREATE INDEX ix_signals_embedding ON signals "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_signals_embedding", table_name="signals")
    op.drop_column("signals", "embedding")
    # The extension is left installed: another table may come to depend on it,
    # and dropping it would be a bigger claim than this migration should make.
```

Add `pgvector>=0.3` and `sentence-transformers>=3` to `pyproject.toml`
dependencies. Add `database_report(session)` to `schema_check.py`: reuse the
existing database/PostGIS probe, query `pg_extension` for `vector`, and return
only component states. Add `embedding` to
`schema_check.EXPECTED_SIGNAL_COLUMNS`, merge the component report into
`build_report()`, and require pgvector in the command's exit condition.

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest apps/api/tests/test_migrations.py packages/backend/tests/test_schema_check.py -v
git add -A && git commit -m "feat(schema): enable pgvector and store signal embeddings"
```

---

## Task 10: The embedding provider

**Files:**
- Create: `packages/backend/src/episignal_backend/ai/embeddings.py`
- Test: `packages/backend/tests/test_embeddings.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_fake_provider_satisfies_the_protocol() -> None:
    assert isinstance(FakeEmbeddingProvider(), EmbeddingProvider)


def test_embedding_text_joins_the_title_and_the_snippet() -> None:
    assert embedding_text("Dengue in Chiang Mai", "Officials reported...") == (
        "Dengue in Chiang Mai\nOfficials reported..."
    )


def test_the_snippet_is_bounded() -> None:
    text = embedding_text("Title", "x" * 5000)

    assert len(text) <= EMBEDDING_SNIPPET_CHARACTERS + len("Title") + 1


def test_vectors_are_normalized_for_cosine() -> None:
    vector = normalize([3.0, 4.0] + [0.0] * 1022)

    assert abs(sum(value * value for value in vector) - 1.0) < 1e-6


def test_a_zero_vector_normalizes_to_itself_rather_than_dividing_by_zero() -> None:
    assert normalize([0.0] * 1024) == [0.0] * 1024


def test_cosine_similarity_of_normalized_vectors_is_the_inner_product() -> None:
    left = normalize([1.0, 1.0] + [0.0] * 1022)

    assert abs(cosine(left, left) - 1.0) < 1e-6
```

- [ ] **Step 2: Run it, then write the module**

```python
"""Sentence embeddings, behind one seam.

Clustering must never import a model library. Everything above this module sees
`EmbeddingProvider`, so a local model can be swapped for a hosted endpoint
without touching a single matching rule.

Vectors are L2-normalized here rather than at query time, so cosine similarity
is an inner product and the pgvector index measures what the code claims.
"""

import math
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

EMBEDDING_DIMENSIONS = 1024
EMBEDDING_SNIPPET_CHARACTERS = 1200


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


def embedding_text(title: str, snippet: str) -> str:
    """What gets embedded: the headline, then the opening.

    The title carries the disease and the place; the opening carries the
    reporting that distinguishes one outbreak from another with the same
    headline shape.
    """
    return f"{title}\n{snippet[:EMBEDDING_SNIPPET_CHARACTERS]}"


def normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        # A zero vector has no direction. Returning it unchanged keeps the
        # caller honest rather than inventing one.
        return list(vector)
    return [value / norm for value in vector]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


class LocalBgeM3Provider:
    """BAAI/bge-m3, loaded once and held for the life of the worker.

    Construction is expensive -- it loads roughly two gigabytes of weights --
    so a provider built per article is a defect, not a slow path. The
    scheduled stage builds one per run and the runner builds one per process.
    """

    def __init__(self, model_name: str = "BAAI/bge-m3", batch_size: int = 16) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self._batch_size = batch_size

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if not texts:
            return ()
        vectors = self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=False,
            show_progress_bar=False,
        )
        return tuple(normalize(vector.tolist()) for vector in vectors)
```

The `sentence_transformers` import is inside `__init__` deliberately: importing
it at module scope would make every test that touches this file pay two
gigabytes of load time.

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_embeddings.py -v
git add -A && git commit -m "feat(ai): embed behind a replaceable provider seam"
```

---

## Task 11: The embedding pass and stage

**Files:**
- Create: `ai/embed.py`, `embed_runner.py`
- Modify: `ai/protocol.py`, `ai/repository.py`, `schedule/*`, `config.py`
- Test: `packages/backend/tests/test_ai_embed.py`

- [ ] **Step 1: Write the failing test**

```python
def test_signals_are_embedded_in_one_batch() -> None:
    repository = EmbedRepository(pending=(FIRST, SECOND, THIRD))
    provider = CountingProvider()

    result = run_embedding(repository, provider, batch_size=16)

    assert result.embedded == 3
    assert provider.calls == 1  # one batch, not three


def test_a_stored_vector_is_normalized() -> None:
    repository = EmbedRepository(pending=(FIRST,))

    run_embedding(repository, CountingProvider(), batch_size=16)

    stored = repository.embeddings[FIRST.id]
    assert abs(sum(v * v for v in stored) - 1.0) < 1e-6


def test_an_already_embedded_signal_is_not_selected() -> None:
    repository = EmbedRepository(pending=())

    assert run_embedding(repository, CountingProvider(), batch_size=16).embedded == 0


def test_a_provider_failure_leaves_the_batch_unembedded_and_countable() -> None:
    repository = EmbedRepository(pending=(FIRST,))

    result = run_embedding(repository, FailingProvider(), batch_size=16)

    assert result.failed == 1
    assert repository.embeddings == {}
```

- [ ] **Step 2: Implement**

`run_embedding(repository, provider, *, batch_size)` selects signals with
`relevant` triage and a null embedding, builds `embedding_text` for each,
calls `provider.embed` once per batch, and writes through
`repository.record_embeddings(mapping)`. No model calls, no cost rows —
embeddings are local and free.

Add `StageName.EMBED = "embed"` after `TRIAGE`, `_embed()` in `stages.py`
constructing **one** provider per run, and settings
`embedding_model: str = "BAAI/bge-m3"`, `embedding_provider: Literal["local"] = "local"`,
`embedding_batch_size: int = 16`.

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_ai_embed.py packages/backend/tests/test_schedule_chains.py -v
git add -A && git commit -m "feat(ai): embed relevant signals in batches"
```

---

## Task 12: Candidate blocking

**Files:**
- Modify: `events/repository.py` (`candidate_events`), `config.py`
- Test: `packages/backend/tests/test_event_repository.py`

- [ ] **Step 1: Write the failing test**

```python
def test_candidates_are_bounded_by_lookback_and_limit(session) -> None:
    repository = SqlAlchemyEventRepository(session)

    candidates = repository.candidate_events(
        CLUSTER, lookback_days=7, limit=20
    )

    assert len(candidates) <= 20
    assert all(c.latest_report_at >= NOW - timedelta(days=7) for c in candidates)


def test_a_different_disease_is_never_a_candidate(session) -> None:
    repository = SqlAlchemyEventRepository(session)

    candidates = repository.candidate_events(DENGUE_CLUSTER, lookback_days=7, limit=20)

    assert MEASLES_EVENT_ID not in {c.id for c in candidates}


def test_a_cluster_without_geography_still_gets_candidates(session) -> None:
    # Missing geography must not prevent a match; it only prevents a conflict.
    repository = SqlAlchemyEventRepository(session)

    assert repository.candidate_events(NO_GEOGRAPHY_CLUSTER, lookback_days=7, limit=20)
```

- [ ] **Step 2: Implement**

`candidate_events` gains `lookback_days` and `limit`, wired from new settings
`event_lookback_days: int = 7` and `event_candidate_limit: int = 20`. The
query filters on the same disease, the same country when both are known, and
`last_updated_at >= now - lookback_days`, ordered by recency, limited.

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_event_repository.py -v
git add -A && git commit -m "feat(events): bound candidate retrieval by lookback and limit"
```

---

## Task 13: Similarity as an additive term

> **Worker correction — 2026-08-30:** O2's `decide` accepts a sequence of
> candidates and resolves the attach/create/refuse ambiguity across that
> sequence. The original examples below treated it as a single-candidate
> boolean API and referred to fields that do not exist. Keep the O2 batch API.
> Add per-candidate rejection reasons to `MatchDecision`, and accept a lazy
> `similarity_for(cluster, candidate)` callback. `decide` must call that
> callback only after the candidate passes every deterministic guard. This
> also corrects Task 14's original instruction to compute cosine before
> calling `decide`, which would violate E5 even if `decide` later refused the
> pair.

**Files:**
- Modify: `events/match.py`, `events/documents.py`
- Test: `packages/backend/tests/test_event_match.py`

- [ ] **Step 1: Write the failing tests — these are the safety tests**

```python
def test_conflicting_admin1_is_refused_before_similarity_is_consulted() -> None:
    # Dengue in Chiang Mai and dengue in Phuket read almost identically.
    calls = []
    decision = decide(
        CHIANG_MAI_CLUSTER,
        [PHUKET_EVENT],
        similarity_for=lambda cluster, event: calls.append(event.event_id) or 0.99,
        threshold=0.80,
    )

    assert decision.action is MatchAction.CREATE
    assert decision.candidate_rejections[PHUKET_EVENT.event_id] is MatchRejection.CONFLICTING_ADMIN1
    assert calls == []


def test_similarity_cannot_veto_a_deterministic_match() -> None:
    # A terse official bulletin shares little vocabulary with the reporting it
    # confirms, and must still attach.
    decision = decide(
        CHIANG_MAI_CLUSTER,
        [CHIANG_MAI_EVENT],
        similarity_for=lambda cluster, event: 0.10,
        threshold=0.80,
    )

    assert decision.action is MatchAction.ATTACH


def test_similarity_raises_the_score_of_a_permitted_pair() -> None:
    low = decide(CHIANG_MAI_CLUSTER, [CHIANG_MAI_EVENT], similarity_for=lambda c, e: 0.10, threshold=0.80)
    high = decide(CHIANG_MAI_CLUSTER, [CHIANG_MAI_EVENT], similarity_for=lambda c, e: 0.95, threshold=0.80)

    assert high.candidate_scores[CHIANG_MAI_EVENT.event_id] > low.candidate_scores[CHIANG_MAI_EVENT.event_id]


def test_a_missing_embedding_falls_back_to_the_deterministic_score() -> None:
    decision = decide(CHIANG_MAI_CLUSTER, [CHIANG_MAI_EVENT], threshold=0.80)

    assert decision.action is MatchAction.ATTACH
    assert decision.candidate_rejections[CHIANG_MAI_EVENT.event_id] is None


def test_a_different_disease_is_refused_with_its_own_reason() -> None:
    calls = []
    decision = decide(
        DENGUE_CLUSTER,
        [MEASLES_EVENT],
        similarity_for=lambda cluster, event: calls.append(event.event_id) or 0.99,
        threshold=0.80,
    )

    assert decision.action is MatchAction.CREATE
    assert decision.candidate_rejections[MEASLES_EVENT.event_id] is MatchRejection.DISEASE_MISMATCH
    assert calls == []
```

- [ ] **Step 2: Implement**

Add a `MatchRejection` StrEnum: `DISEASE_MISMATCH`, `CONFLICTING_ADMIN1`,
`OUTSIDE_TIME_WINDOW`, `TOO_FAR`, `SCORE_BELOW_THRESHOLD`. `MatchDecision`
gains a `candidate_rejections` mapping parallel to `candidate_scores`. `decide`
gains the optional lazy `similarity_for` callback described above.

The order is the invariant:

```python
    # Deterministic guards first, and they are the only thing that can refuse.
    # Similarity is consulted afterwards and only ever adds confidence: a pair
    # these rules accept must not be split because two publishers chose
    # different words for one outbreak.
    if not disease_compatible(...):
        reject(candidate, MatchRejection.DISEASE_MISMATCH)
        continue
    if both_admin1_known_and_different(...):
        reject(candidate, MatchRejection.CONFLICTING_ADMIN1)
        continue
    if not temporally_compatible(...):
        reject(candidate, MatchRejection.OUTSIDE_TIME_WINDOW)
        continue
    ...
    score = deterministic_score
    similarity = similarity_for(cluster, candidate) if similarity_for else None
    if similarity is not None:
        score = min(1.0, score + SIMILARITY_WEIGHT * max(0.0, similarity))
```

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_event_match.py packages/backend/tests/test_event_cluster.py -v
git add -A && git commit -m "feat(events): let similarity add confidence, never veto"
```

---

## Task 14: Wire similarity into assembly, with decision logging

**Files:**
- Modify: `events/assemble.py`, `events/repository.py`
- Test: `packages/backend/tests/test_event_assemble.py`

- [ ] **Step 1: Write the failing test**

```python
def test_every_match_decision_is_logged_with_its_reason(caplog) -> None:
    run_event_assembly(repository, ...)

    assert "matched event" in caplog.text
    assert "similarity=" in caplog.text
    assert "reason=conflicting_admin1" in caplog.text
```

- [ ] **Step 2: Implement**

`signals_to_match` returns the signal's embedding. Assembly gives `decide` a
lazy provider that computes cosine against each candidate event's
representative embedding. Because `decide` invokes it only after deterministic
guards pass, refused pairs never consult embeddings. Every decision is logged
at INFO with the event id, the similarity, and the reason on refusal. Event
creation and attachment log likewise.

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_event_assemble.py -v
git add -A && git commit -m "feat(events): log every clustering decision and its reason"
```

---

## Task 15: The four calibration fixtures

**Files:**
- Create: `packages/backend/tests/fixtures/calibration/*.json`
- Create: `packages/backend/tests/test_event_calibration.py`

- [ ] **Step 1: Write the tests**

One test per scenario from the brief, run against the deterministic matcher
with a **stubbed** embedding provider returning fixed vectors, so no model is
loaded and no credits are spent:

```python
def test_three_chiang_mai_dengue_reports_become_one_event() -> None:
    assert events_from(CHIANG_MAI_THREE) == 1


def test_chiang_mai_and_phuket_dengue_stay_separate() -> None:
    assert events_from(CHIANG_MAI_AND_PHUKET) == 2


def test_dengue_and_measles_in_one_province_stay_separate() -> None:
    assert events_from(DENGUE_AND_MEASLES) == 2


def test_a_wednesday_follow_up_joins_mondays_event_and_updates_it() -> None:
    outcome = assemble(MONDAY_THEN_WEDNESDAY)

    assert outcome.events == 1
    assert outcome.articles_attached == 2
    assert outcome.resummarized is True
```

The fourth assertion is written now and expected to fail until Task 23; mark it
`@pytest.mark.xfail(reason="resummarization lands in Task 23", strict=True)` and
remove the marker there.

- [ ] **Step 2: Run, then commit**

```bash
uv run pytest packages/backend/tests/test_event_calibration.py -v
git add -A && git commit -m "test: pin the four event-matching calibration scenarios"
```

---

## Task 16: Phase B checkpoint

- [ ] **Step 1: Run the full verification**

```bash
corepack pnpm verify
```

- [ ] **Step 2: Embed a live sample and measure**

Run `corepack pnpm embed:signals` against the live database on a bounded batch.
Record: how many signals embedded, wall clock, and the observed cosine
similarity distribution for pairs the deterministic matcher already agreed on.
That distribution is what `EVENT_MATCH_THRESHOLD=0.80` should later be
calibrated against.

- [ ] **Step 3: Stop and report.** Do not start Phase C until acknowledged.

---

# Phase C — Event summaries

## Task 17: The summary history table

**Files:**
- Create: `database/migrations/versions/20260830_0019_event_summaries.py`
- Modify: `models/event.py`, `models/ai.py`, `schema_check.py`
- Test: `apps/api/tests/test_migrations.py`

- [ ] **Step 1: Write the failing test**

```python
def test_summary_history_records_the_articles_it_used() -> None:
    sql = render_offline("upgrade", "20260830_0018:20260830_0019")

    assert "event_summary_history" in sql
    assert "article_ids_used" in sql
    assert "ai_requests" in sql and "event_id" in sql
```

- [ ] **Step 2: Implement**

`event_summary_history`: `id`, `event_id` (FK cascade), `summary_version`
(int), `summary_json` (JSONB), `model` (text), `article_ids_used`
(`ARRAY(Uuid)`), `created_at`. Unique on `(event_id, summary_version)`.
`events` gains `summary_version`, `last_summarized_at`, `summary_model`,
`article_count`, `official_source_count`, and the structured fields the brief
names that are not already present. `ai_requests` gains a nullable `event_id`.

Downgrade refuses if any `event_summary_history` row exists, following
`20260829_0014`'s precedent: a summary history is audit evidence.

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest apps/api/tests/test_migrations.py packages/backend/tests/test_schema_check.py -v
git add -A && git commit -m "feat(schema): version event summaries with their evidence"
```

---

## Task 18: The event summary contract

**Files:**
- Create: `events/summary_schema.py`
- Test: `packages/backend/tests/test_event_summary_schema.py`

- [ ] **Step 1: Write the failing test**

```python
def test_every_epidemiological_number_may_be_absent() -> None:
    summary = EventSummary.model_validate(MINIMAL)

    assert summary.cases is None
    assert summary.deaths is None


def test_a_case_count_no_observation_supports_is_rejected() -> None:
    with pytest.raises(Rejected) as error:
        validate_event_summary(json.dumps(CLAIMS_500_CASES), observations=OBSERVATIONS_MAX_42)

    assert error.value.reason is RejectionReason.UNGROUNDED


def test_a_count_matching_an_observation_is_accepted() -> None:
    summary = validate_event_summary(json.dumps(CLAIMS_42_CASES), observations=OBSERVATIONS_MAX_42)

    assert summary.cases == 42


def test_conflicting_reports_are_preserved_as_uncertainty() -> None:
    summary = validate_event_summary(json.dumps(CONFLICTING), observations=OBSERVATIONS_MAX_42)

    assert summary.uncertainties


def test_a_summary_carrying_a_person_is_refused() -> None:
    with pytest.raises(Rejected) as error:
        validate_event_summary(json.dumps(WITH_PHONE_NUMBER), observations=OBSERVATIONS_MAX_42)

    assert error.value.reason is RejectionReason.PRIVACY
```

- [ ] **Step 2: Implement**

`EventSummary` mirrors the brief's JSON exactly, every numeric field
`int | None`. `validate_event_summary(content, observations)` parses, then
checks each numeric claim against the maximum recorded in
`event_observations` — a summary may report a number an observation carries;
it may not exceed every one of them. Reuse `check_privacy` from `ai/validate.py`
rather than writing a second one.

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_event_summary_schema.py -v
git add -A && git commit -m "feat(events): ground an event summary in its observations"
```

---

## Task 19: Representative article selection

**Files:**
- Modify: `events/summarize.py`
- Test: `packages/backend/tests/test_event_summarize.py`

- [ ] **Step 1: Write the failing test**

```python
def test_an_official_source_is_always_selected() -> None:
    chosen = select_representative_articles(ARTICLES_WITH_ONE_OFFICIAL, max_articles=3)

    assert OFFICIAL_ID in {a.id for a in chosen}


def test_no_more_than_the_maximum_is_returned() -> None:
    assert len(select_representative_articles(FIFTY_ARTICLES, max_articles=6)) == 6


def test_near_identical_copies_are_not_both_selected() -> None:
    chosen = select_representative_articles(TWO_SYNDICATED_AND_ONE_ORIGINAL, max_articles=6)

    assert len(chosen) == 2


def test_the_most_recent_report_is_selected() -> None:
    chosen = select_representative_articles(FIFTY_ARTICLES, max_articles=6)

    assert NEWEST_ID in {a.id for a in chosen}


def test_selection_is_deterministic() -> None:
    first = select_representative_articles(FIFTY_ARTICLES, max_articles=6)
    second = select_representative_articles(FIFTY_ARTICLES, max_articles=6)

    assert [a.id for a in first] == [a.id for a in second]
```

- [ ] **Step 2: Implement** the ranked selection from spec E6, excluding any
article whose cosine similarity to an already-selected one exceeds
`NEAR_DUPLICATE_THRESHOLD`. Ties break on signal id so the choice is stable.

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_event_summarize.py -v
git add -A && git commit -m "feat(events): choose the sources an event summary should read"
```

---

## Task 20: Material-update detection

**Files:**
- Modify: `events/summarize.py`, `config.py`
- Test: `packages/backend/tests/test_event_summarize.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_new_event_is_always_summarized() -> None:
    assert needs_summary(NEW_EVENT, thresholds=THRESHOLDS).triggered is True


def test_an_official_source_triggers_a_resummary() -> None:
    assert needs_summary(EVENT_WITH_NEW_OFFICIAL, thresholds=THRESHOLDS).reason == "official_source_added"


def test_an_unchanged_event_is_never_resummarized() -> None:
    assert needs_summary(QUIET_EVENT, thresholds=THRESHOLDS).triggered is False


def test_age_alone_does_not_trigger_a_resummary() -> None:
    # Age is not information. Re-summarizing an event nothing has said anything
    # new about spends money to reproduce the same paragraph.
    assert needs_summary(OLD_BUT_QUIET_EVENT, thresholds=THRESHOLDS).triggered is False


def test_age_with_new_evidence_does_trigger() -> None:
    assert needs_summary(OLD_WITH_ONE_NEW_ARTICLE, thresholds=THRESHOLDS).reason == "stale_with_new_evidence"


def test_enough_new_articles_trigger_a_resummary() -> None:
    assert needs_summary(EVENT_WITH_THREE_NEW, thresholds=THRESHOLDS).reason == "article_count"


def test_a_semantically_novel_article_triggers_a_resummary() -> None:
    assert needs_summary(EVENT_WITH_NOVEL_ARTICLE, thresholds=THRESHOLDS).reason == "novel_article"


def test_a_forced_request_overrides_every_heuristic() -> None:
    assert needs_summary(QUIET_EVENT, thresholds=THRESHOLDS, forced=True).triggered is True
```

- [ ] **Step 2: Implement** exactly the conditions in spec E6, with settings
`resummary_new_article_count: int = 3`, `resummary_max_age_hours: int = 24`,
`novel_article_similarity_threshold: float = 0.88`.

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_event_summarize.py -v
git add -A && git commit -m "feat(events): summarize only when something changed"
```

---

## Task 21: The DeepSeek summarization pass

**Files:**
- Modify: `events/summarize.py`, `events/repository.py`, `ai/prompts.py`
- Test: `packages/backend/tests/test_event_summarize.py`

- [ ] **Step 1: Write the failing test**

```python
def test_an_accepted_summary_is_stored_with_its_version_and_evidence() -> None:
    repository = SummaryRepository(events=(NEW_EVENT,))
    model = ScriptedModel([ChatResponse(content=GOOD_SUMMARY, latency_ms=10)])

    result = run_summarization(repository, model, guards=guards(), now=lambda: NOW)

    assert result.summarized == 1
    assert repository.events[EVENT_ID].summary_version == 1
    assert repository.history[0].article_ids_used == tuple(a.id for a in CHOSEN)
    assert repository.history[0].model == "deepseek/deepseek-v4-flash-0731"


def test_a_second_summary_increments_the_version_and_keeps_the_first() -> None:
    ...
    assert [h.summary_version for h in repository.history] == [1, 2]


def test_the_cost_row_names_the_event() -> None:
    run_summarization(repository, model, guards=guards(), now=lambda: NOW)

    assert repository.requests[0].event_id == EVENT_ID
    assert repository.requests[0].purpose is AiPurpose.EVENT_SUMMARY


def test_a_rejected_summary_leaves_the_previous_one_standing() -> None:
    # A backfill never destroys a good old answer to store a bad new one, and
    # neither does a resummary.
    ...
    assert repository.events[EVENT_ID].summary_version == 1


def test_rerunning_the_pass_produces_no_second_summary() -> None:
    run_summarization(repository, model, guards=guards(), now=lambda: NOW)
    second = run_summarization(repository, model, guards=guards(), now=lambda: NOW)

    assert second.summarized == 0
    assert len(repository.history) == 1
```

- [ ] **Step 2: Implement** the pass: select events `needs_summary` returns true
for, choose representatives, build the prompt from their titles, briefs and
publication times, climb a ladder scoped to `AiPurpose.EVENT_SUMMARY`, validate
against observations, and store the summary plus a history row in one
transaction. Idempotence comes from `last_summarized_at` and the article count
at the time of summarizing, both written in that same transaction.

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_event_summarize.py -v
git add -A && git commit -m "feat(events): write one grounded narrative per event"
```

---

## Task 22: The `summarize` stage, runner, and force flag

**Files:**
- Modify: `schedule/documents.py`, `chains.py`, `stages.py`; create `summarize_runner.py`
- Test: `packages/backend/tests/test_schedule_chains.py`, `test_summarize_runner.py`

- [ ] **Step 1: Write the failing test**

```python
def test_summarization_runs_last() -> None:
    assert DAILY_CHAIN[-1] is StageName.SUMMARIZE


def test_the_runner_can_force_one_event() -> None:
    assert parse_arguments(["--event", str(EVENT_ID), "--force"]).forced is True
```

- [ ] **Step 2: Implement**, adding `StageName.SUMMARIZE` after `MATCH` and
`summarize:events` to `package.json`, with `--event` and `--force` arguments
for the operator's manual job.

- [ ] **Step 3: Remove the `xfail` marker** from Task 15's fourth calibration
test and confirm it now passes.

- [ ] **Step 4: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_schedule_chains.py packages/backend/tests/test_summarize_runner.py packages/backend/tests/test_event_calibration.py -v
git add -A && git commit -m "feat(schedule): summarize events at the end of the chain"
```

---

## Task 23: Cost reporting

**Files:**
- Modify: `ai/spend.py`, `spend_runner.py`
- Test: `packages/backend/tests/test_spend_report.py`

- [ ] **Step 1: Write the failing test**

```python
def test_the_report_answers_the_five_questions(session) -> None:
    summary = trailing_spend(session, window_days=30, now=NOW)

    assert summary.cost_today == Decimal("0.004000")
    assert summary.cost_this_month == Decimal("0.120000")
    assert summary.cost_per_thousand_candidates == Decimal("0.250000")
    assert summary.cost_per_event == Decimal("0.030000")
    assert summary.volume_by_purpose["triage"] == 17
    assert summary.volume_by_purpose["event_summary"] == 2


def test_cost_per_event_is_zero_rather_than_undefined_with_no_events(session) -> None:
    assert trailing_spend(session, window_days=30, now=NOW).cost_per_event == Decimal("0")
```

- [ ] **Step 2: Implement** the five aggregates, guarding every division against
zero. Print them in `spend_runner`.

- [ ] **Step 3: Run the tests, then commit**

```bash
uv run pytest packages/backend/tests/test_spend_report.py -v
git add -A && git commit -m "feat(spend): answer cost per candidate and per event"
```

---

## Task 24: Documentation and configuration

**Files:**
- Create: `docs/news-event-pipeline.md`
- Modify: `apps/api/.env.example`, `CONTEXT.md`
- Create: `docs/adr/2026-08-30-similarity-adds-confidence-never-vetoes.md`

- [ ] **Step 1: Write `docs/news-event-pipeline.md`**

Covering, in this order: the processing flow stage by stage; the three AI models
and what each is for; the clustering rules with the deterministic guards stated
first; every threshold with its default and what raising or lowering it does;
how to tune a threshold against the Phase B similarity distribution; failure
recovery per status (`triage_status = failed`, `retrieval_failed`,
`extraction_rejected`); and how to read AI cost from `spend:report`.

- [ ] **Step 2: Add every new variable to `apps/api/.env.example`**

```
EPISIGNAL_EMBEDDING_MODEL=BAAI/bge-m3
EPISIGNAL_EMBEDDING_PROVIDER=local
EPISIGNAL_EMBEDDING_BATCH_SIZE=16
EPISIGNAL_EVENT_LOOKBACK_DAYS=7
EPISIGNAL_EVENT_CANDIDATE_LIMIT=20
EPISIGNAL_NEAR_DUPLICATE_THRESHOLD=0.92
EPISIGNAL_EVENT_MATCH_THRESHOLD=0.80
EPISIGNAL_NOVEL_ARTICLE_SIMILARITY_THRESHOLD=0.88
EPISIGNAL_RESUMMARY_NEW_ARTICLE_COUNT=3
EPISIGNAL_RESUMMARY_MAX_AGE_HOURS=24
EPISIGNAL_AI_TRIAGE_BATCH_LIMIT=200
```

- [ ] **Step 3: Write the ADR** recording E5 — similarity adds confidence and
never vetoes — with the Chiang Mai / Phuket case as its worked example and the
condition that would reverse it.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "docs: document the event pipeline and its thresholds"
```

---

## Task 25: End-to-end fixture run

**Files:**
- Create: the `test-pipeline` development command
- Test: `packages/backend/tests/test_pipeline_fixture.py`

- [ ] **Step 1: Build the command**

```bash
uv run --package episignal-backend python -m episignal_backend.pipeline_runner test-pipeline
```

It processes a committed fixture of ~20 synthetic articles through every stage
with a stubbed embedding provider and a scripted model, spending nothing, and
prints exactly the shape the brief asks for:

```
20 articles ingested
3 exact duplicates removed
17 triaged
8 relevant
8 embedded
3 epidemiological events created
2 event summaries generated
AI calls:
  triage = 17
  event_summary = 2
```

The fixture is clearly labelled synthetic and is never presented as live proof.

- [ ] **Step 2: Assert the output shape in a test**, so the command cannot rot.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat(dev): run the whole funnel over a synthetic fixture"
```

---

## Task 26: Review, verify, live proof, report

- [ ] **Step 1: Load `code-review`** and act on it.

- [ ] **Step 2: Load `verify-and-stop`** and run the real command.

```bash
corepack pnpm verify
```

- [ ] **Step 3: Capture live proof**

Migrate and seed, run the chain once, and record: triage counts and how many
produced a usable disease and country; embedding count and wall clock; events
created and attached, each with its similarity and decision reason; summaries
generated with their trigger reasons; one full `event_summary_history` row
showing the articles used; and `spend:report`'s five aggregates against the
pre-run figures.

Do not resolve live review cases for demonstration.

- [ ] **Step 4: Write the report** to
`docs/reports/2026-08-30-event-surveillance-report.md` with the verification
output verbatim, the live numbers, every deviation from this plan with its
reason, and — required by the brief — **files changed, migrations added, tests
run, remaining limitations, and the recommended next calibration step.**

The calibration recommendation must name a concrete threshold and the
distribution that justifies moving it, not a general intention to tune.

- [ ] **Step 5: Update `STATUS.md`** Verified baseline with the commit the
verification actually ran at.

- [ ] **Step 6: Commit and hand back.** Do not mark `R` verified.

---

## Scope guard

Do not: create a `news_articles` table; create an `ai_usage` table; store a
`snippet` column; implement HDBSCAN or DBSCAN; let embedding similarity refuse
a pair the deterministic rules accept; merge two events with known and
different `admin1`; re-summarize an event with no new evidence; delete any
signal at any stage; or change the geocode ladder, the review queue, the radar
read model, or anything `O2` settled.

**If the plan turns out to be wrong, stop and report.** Correcting a plan is
planner work.

---

## Self-review notes

Spec coverage: E1 → Tasks 4–8; E2 → Tasks 2, 3; E3 → Tasks 4–6; E4 → Tasks
9–11; E5 → Tasks 12–15 (the safety tests are Task 13's); E6 → Tasks 17–22;
E7 → Tasks 1, 7, 17, 23; E8 → the scope guard. Acceptance → Tasks 15, 25, 26.

Type consistency: `TriageVerdict` is produced in Task 4, prompted in Task 5,
stored in Task 6, and read as the blocking key in Task 12. `EmbeddingProvider`
is defined in Task 10 and is the only embedding type Tasks 11, 14, 19 and 25
know. `MatchRejection` is defined in Task 13 and logged in Task 14.

Two risks the worker should watch. First, `sentence-transformers` pulls torch —
confirm the install size and CPU-only wheel resolution at Task 9 before Task 10
depends on it, and report if the footprint is unacceptable. Second, the HNSW
index is created without `lists`/`ef_construction` tuning; that is deliberate
for a table this size, and Task 16's measurement is where evidence for tuning
would come from.
