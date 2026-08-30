# English Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every extraction carries an English title and a five-bullet brief in fixed slot order, and the signals extracted before this item can be brought up to that shape by one bounded command.

**Architecture:** The model's answer contract (`ai/schema.py`) replaces its free-form `summary` with `title_english` and a `brief` of exactly five slotted points, enforced by a validator that `parse_extraction` already converts into a `SHAPE` rejection. The repository stamps a schema version into the stored JSONB and writes the joined brief into `signals.summary`. Reading our own history stays possible through a tolerant subclass. A new `run_backfill` reuses the extraction pass's per-signal path against a different selection query, and returns each re-extracted row to `extracted` so geocoding and matching run again.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2 (JSONB), pytest, mypy `strict`, ruff. No migration: `signals.ai_extraction` is already JSONB.

**Spec:** [docs/superpowers/specs/2026-08-28-english-brief-design.md](../specs/2026-08-28-english-brief-design.md)

---

## Before you start

Read the spec. Then read these three files, because every task touches at least one of them:

- `packages/backend/src/episignal_backend/ai/schema.py` — the contract with the model.
- `packages/backend/src/episignal_backend/ai/validate.py` — every check an answer passes, in order.
- `packages/backend/src/episignal_backend/ai/extract.py` — the pass that asks, validates, and stores.

Two rules from `AGENTS.md` that this item leans on hard:

- **Test first.** Write the failing test, run it, watch it fail for the reason you expect, then implement.
- **Never infer.** Nothing in this item may cause the system to state a fact the article does not state. A brief point about something the article never mentioned is `reported: false` with text that says so.

Run one test with `uv run pytest <path>::<name> -v`. Run everything with `uv run pytest`. The gate is `corepack pnpm verify`.

## File structure

**Modified:**

| File | Responsibility after this item |
| --- | --- |
| `packages/backend/src/episignal_backend/ai/schema.py` | The model's contract, plus the slot vocabulary, the version constants, and the tolerant reader for stored payloads. |
| `packages/backend/src/episignal_backend/ai/validate.py` | Unchanged in structure; privacy scans the title and the brief instead of the summary. |
| `packages/backend/src/episignal_backend/ai/prompts.py` | Extraction rules gain the English, five-slot, and untranslated-span rules. |
| `packages/backend/src/episignal_backend/ai/protocol.py` | `AiRepository` gains `awaiting_backfill`. |
| `packages/backend/src/episignal_backend/ai/repository.py` | Selects stale extractions; stamps the version; writes the joined brief. |
| `packages/backend/src/episignal_backend/ai/extract.py` | One shared per-signal pass, driven by two selections: new work and stale work. |
| `packages/backend/src/episignal_backend/events/repository.py` | Reads stored extractions through the tolerant model. |
| `package.json` | `extract:backfill`. |
| `apps/api/.env.example` | Documents `EPISIGNAL_OPENROUTER_API_KEY`. |
| `CONTEXT.md` | *Brief*, *slot*, *English title*. |

**Created:**

| File | Responsibility |
| --- | --- |
| `packages/backend/src/episignal_backend/backfill_runner.py` | Entry point for `pnpm extract:backfill`. Counts only on stdout, never a key or a body. |
| `packages/backend/tests/test_backfill_runner.py` | Argument parsing, exit codes, and the secrecy posture. |
| `docs/reports/2026-08-28-subproject-c2-report.md` | The completion report, with the real verification output. |

---

### Task 1: The slot vocabulary

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/schema.py`
- Test: `packages/backend/tests/test_ai_schema.py`

- [ ] **Step 1: Write the failing tests**

Add to `packages/backend/tests/test_ai_schema.py`, and extend the import at the top of the file to `from episignal_backend.ai.schema import BRIEF_SLOT_COUNT, BRIEF_SLOTS, BriefPoint, BriefSlot, Extraction, GroundedCount, GroundedFlag`:

```python
def test_the_slots_are_ordered_as_an_epidemiologist_reads_them() -> None:
    assert BRIEF_SLOTS == (
        BriefSlot.WHAT_WHERE,
        BriefSlot.COUNTS,
        BriefSlot.TIMING,
        BriefSlot.SPREAD,
        BriefSlot.REPORTING,
    )
    assert BRIEF_SLOT_COUNT == 5


def test_a_point_may_report_an_absence() -> None:
    point = BriefPoint.model_validate(
        {"slot": "counts", "text": "No case count reported.", "reported": False}
    )

    assert point.reported is False
    assert point.slot is BriefSlot.COUNTS


def test_a_point_must_say_something_even_when_nothing_was_reported() -> None:
    with pytest.raises(ValidationError):
        BriefPoint.model_validate({"slot": "counts", "text": "   ", "reported": False})


def test_a_point_rejects_a_slot_nobody_defined() -> None:
    with pytest.raises(ValidationError):
        BriefPoint.model_validate({"slot": "vibes", "text": "Something happened.", "reported": True})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest packages/backend/tests/test_ai_schema.py -v -k "slot or point"`
Expected: FAIL — `ImportError: cannot import name 'BRIEF_SLOTS'`.

- [ ] **Step 3: Implement**

In `packages/backend/src/episignal_backend/ai/schema.py`, add `from enum import StrEnum` to the imports and insert this above `class GroundedCount`:

```python
BRIEF_POINT_MAX_CHARACTERS = 200
TITLE_MAX_CHARACTERS = 300


class BriefSlot(StrEnum):
    """One of the five questions a brief answers, in the order it is asked."""

    WHAT_WHERE = "what_where"
    COUNTS = "counts"
    TIMING = "timing"
    SPREAD = "spread"
    REPORTING = "reporting"


# Declaration order is the required order of a brief, so the enum is the
# authority on both which slots exist and what sequence they come in.
BRIEF_SLOTS: tuple[BriefSlot, ...] = tuple(BriefSlot)
BRIEF_SLOT_COUNT = len(BRIEF_SLOTS)


class BriefPoint(BaseModel):
    """One bullet of a brief.

    `reported` is false when the article never addressed this slot. The text
    still has to say something — it says what is missing — because an empty
    bullet and an unreported fact would look identical to a reader.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    slot: BriefSlot
    text: str = Field(min_length=1, max_length=BRIEF_POINT_MAX_CHARACTERS)
    reported: bool

    @field_validator("text")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("a brief point must say something, including an absence")
        return collapsed
```

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest packages/backend/tests/test_ai_schema.py -v -k "slot or point"`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/schema.py packages/backend/tests/test_ai_schema.py
git commit -m "feat: add the brief's slot vocabulary" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The extraction carries an English title and a brief

This is the breaking task. `summary` leaves the contract, so every payload in the
test suite changes in the same commit. Do not split it — a commit where the
suite is red is a commit nobody can bisect through.

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/schema.py`
- Modify: `packages/backend/tests/test_ai_schema.py`
- Modify: `packages/backend/tests/test_ai_validate.py`
- Modify: `packages/backend/tests/test_ai_repository.py`
- Modify: `packages/backend/tests/test_ai_extract.py`
- Modify: `packages/backend/tests/fixtures/ai_extraction_response.json`
- Modify: `packages/backend/tests/fixtures/ai_ungrounded_response.json`

- [ ] **Step 1: Write the failing tests**

In `packages/backend/tests/test_ai_schema.py`, replace the `minimal` helper with this one, which is the canonical payload every other test in this plan reuses:

```python
def brief() -> list[dict[str, object]]:
    return [
        {"slot": "what_where", "text": "Cholera in Luanda province, Angola.", "reported": True},
        {"slot": "counts", "text": "327 confirmed cases and 14 deaths.", "reported": True},
        {"slot": "timing", "text": "Figures are as of 25 August 2026.", "reported": True},
        {"slot": "spread", "text": "All cases were acquired locally.", "reported": True},
        {
            "slot": "reporting",
            "text": "Reported by the health ministry; not independently verified.",
            "reported": True,
        },
    ]


def minimal(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "signal_type": "outbreak_report",
        "source_language": "en",
        "title_english": "Angola reports growing cholera outbreak in Luanda",
        "brief": brief(),
        "disease": {"name": "Cholera", "confidence": 0.97},
        "pathogen": None,
        "locations": [{"role": "primary", "country": "Angola", "place_name": "Luanda"}],
        "epidemiology": {"confirmed_cases": {"value": 327, "source_span": "327 confirmed cases"}},
        "dates": {"data_as_of": "2026-08-25"},
        "transmission": None,
        "confidence": 0.94,
    }
    payload.update(overrides)
    return payload
```

Then add these tests:

```python
def test_an_extraction_carries_an_english_title_and_five_bullets() -> None:
    extraction = Extraction.model_validate(minimal())

    assert extraction.title_english == "Angola reports growing cholera outbreak in Luanda"
    assert extraction.source_language == "en"
    assert tuple(point.slot for point in extraction.brief) == BRIEF_SLOTS


def test_a_brief_missing_a_slot_is_rejected() -> None:
    short = brief()[:4]

    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(brief=short))


def test_a_brief_with_a_repeated_slot_is_rejected() -> None:
    repeated = brief()
    repeated[3] = dict(repeated[1])

    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(brief=repeated))


def test_a_brief_out_of_slot_order_is_rejected_rather_than_sorted() -> None:
    shuffled = brief()
    shuffled[0], shuffled[1] = shuffled[1], shuffled[0]

    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(brief=shuffled))


def test_the_free_form_summary_is_no_longer_part_of_the_contract() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(summary="Cholera in Angola."))


def test_a_blank_english_title_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(title_english="   "))


def test_an_unknown_source_language_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Extraction.model_validate(minimal(source_language="portuguese"))


def test_an_unsure_source_language_is_stored_as_absence() -> None:
    extraction = Extraction.model_validate(minimal(source_language=None))

    assert extraction.source_language is None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest packages/backend/tests/test_ai_schema.py -v`
Expected: FAIL — `Extra inputs are not permitted` for `title_english`, `brief`, and `source_language`.

- [ ] **Step 3: Implement the schema change**

In `packages/backend/src/episignal_backend/ai/schema.py`: add `import re` at the top, delete `SUMMARY_MAX_CHARACTERS = 400`, and replace the `summary` field and its `collapse_summary` validator on `Extraction` with:

```python
    source_language: str | None = None
    title_english: str = Field(min_length=1, max_length=TITLE_MAX_CHARACTERS)
    brief: tuple[BriefPoint, ...]
```

placing `signal_type` first and the three new fields immediately after it, then add these validators to `Extraction` in place of `collapse_summary`:

```python
    @field_validator("source_language")
    @classmethod
    def language_is_a_code(cls, value: str | None) -> str | None:
        # Null means the model was unsure, which is recorded rather than guessed.
        if value is None:
            return None
        code = value.strip().lower()
        if not re.fullmatch(r"[a-z]{2}", code):
            raise ValueError("source_language must be an ISO 639-1 two-letter code or null")
        return code

    @field_validator("title_english")
    @classmethod
    def collapse_title(cls, value: str) -> str:
        collapsed = " ".join(value.split())
        if not collapsed:
            raise ValueError("title_english must not be blank")
        return collapsed

    @field_validator("brief")
    @classmethod
    def brief_fills_every_slot_in_order(cls, value: tuple[BriefPoint, ...]) -> tuple[BriefPoint, ...]:
        # Rejected, never re-ordered. A model that returned the slots in its own
        # order did not follow the contract, and quietly sorting its answer
        # teaches the next reader that the order was never load-bearing.
        if tuple(point.slot for point in value) != BRIEF_SLOTS:
            raise ValueError("brief must carry exactly one point per slot, in slot order")
        return value
```

- [ ] **Step 4: Update every other payload in the suite**

`packages/backend/tests/fixtures/ai_extraction_response.json` — replace the `"summary"` line with:

```json
  "source_language": "en",
  "title_english": "Angola reports growing cholera outbreak in Luanda province",
  "brief": [
    { "slot": "what_where", "text": "Cholera in Luanda province, Angola.", "reported": true },
    { "slot": "counts", "text": "327 confirmed of 400 total cases, 14 deaths.", "reported": true },
    { "slot": "timing", "text": "Figures are as of 25 August 2026.", "reported": true },
    { "slot": "spread", "text": "All cases were acquired locally.", "reported": true },
    {
      "slot": "reporting",
      "text": "Reported by Angola's health ministry; not independently verified.",
      "reported": true
    }
  ],
```

`packages/backend/tests/fixtures/ai_ungrounded_response.json` — make the same replacement, keeping the rest of that file exactly as it is, so the only reason it fails validation is still its ungrounded span.

`packages/backend/tests/test_ai_validate.py` — in both `GROUNDED` and `grounded_payload()`, replace the single `"summary"` entry with these three:

```python
    "source_language": "en",
    "title_english": "Angola reports growing cholera outbreak in Luanda",
    "brief": [
        {"slot": "what_where", "text": "Cholera in Luanda province, Angola.", "reported": True},
        {"slot": "counts", "text": "327 confirmed cases and 14 deaths.", "reported": True},
        {"slot": "timing", "text": "Figures are as of 25 August 2026.", "reported": True},
        {"slot": "spread", "text": "All cases were acquired locally.", "reported": True},
        {
            "slot": "reporting",
            "text": "Reported by the health ministry; not independently verified.",
            "reported": True,
        },
    ],
```

In `test_a_summary_carrying_a_telephone_number_is_rejected`, rename the test to `test_a_brief_carrying_a_telephone_number_is_rejected` and replace its body's mutation with:

```python
    payload = grounded_payload()
    points = list(payload["brief"])  # type: ignore[call-overload]
    points[4] = {
        "slot": "reporting",
        "text": "Call the family on +244 923 555 0142 for details.",
        "reported": True,
    }
    payload["brief"] = points
```

`packages/backend/tests/test_ai_repository.py` — replace the `extraction()` helper's payload with:

```python
def extraction() -> Extraction:
    return Extraction.model_validate(
        {
            "signal_type": "outbreak_report",
            "source_language": "en",
            "title_english": "Cholera outbreak reported in Luanda",
            "brief": [
                {"slot": "what_where", "text": "Cholera in Luanda, Angola.", "reported": True},
                {"slot": "counts", "text": "No case count reported.", "reported": False},
                {"slot": "timing", "text": "No date reported.", "reported": False},
                {"slot": "spread", "text": "No transmission detail reported.", "reported": False},
                {"slot": "reporting", "text": "Reported by local media.", "reported": True},
            ],
            "confidence": 0.9,
        }
    )
```

`packages/backend/tests/test_ai_extract.py` — in `FRENCH_ANSWER`, replace the `"summary"` entry with the English brief for a French article, which is the case this whole item exists for:

```python
        "source_language": "fr",
        "title_english": "Cholera outbreak spreads in Luanda province, Angola",
        "brief": [
            {"slot": "what_where", "text": "Cholera in Luanda province, Angola.", "reported": True},
            {"slot": "counts", "text": "327 confirmed cases and 14 deaths.", "reported": True},
            {"slot": "timing", "text": "Figures are as of 25 August 2026.", "reported": True},
            {"slot": "spread", "text": "All cases were acquired locally.", "reported": True},
            {"slot": "reporting", "text": "Reported by local media.", "reported": True},
        ],
```

leaving every `source_span` in that payload in French, untouched.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest`
Expected: PASS. If a test outside `ai/` fails, it is constructing an `Extraction` — fix its payload the same way. Do not relax the schema to make a test pass.

- [ ] **Step 6: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/schema.py packages/backend/tests
git commit -m "feat: replace the free-form summary with an English title and a brief" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Privacy scans the title and the brief

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/validate.py:126-134`
- Test: `packages/backend/tests/test_ai_validate.py`

- [ ] **Step 1: Write the failing test**

```python
def test_an_english_title_carrying_an_email_address_is_rejected() -> None:
    payload = grounded_payload()
    payload["title_english"] = "Write to outbreak.desk@example.org for the case list"

    with pytest.raises(Rejected) as error:
        validate_extraction(json.dumps(payload), BODY)

    assert error.value.reason is RejectionReason.PRIVACY
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest packages/backend/tests/test_ai_validate.py::test_an_english_title_carrying_an_email_address_is_rejected -v`
Expected: FAIL — no `Rejected` raised, because `check_privacy` still scans a field that no longer exists.

- [ ] **Step 3: Implement**

In `packages/backend/src/episignal_backend/ai/validate.py`, replace the first line of `check_privacy`:

```python
def check_privacy(extraction: Extraction) -> None:
    candidates = [extraction.title_english]
    candidates.extend(point.text for point in extraction.brief)
    candidates.extend(
        location.place_name for location in extraction.locations if location.place_name
    )
```

- [ ] **Step 4: Run the privacy tests**

Run: `uv run pytest packages/backend/tests/test_ai_validate.py -v -k "privacy or telephone or email"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/validate.py packages/backend/tests/test_ai_validate.py
git commit -m "fix: scan the title and the brief for contact details" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The prompt asks for English and for five slots

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/prompts.py:17-28`
- Test: `packages/backend/tests/test_ai_prompts.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_extraction_prompt_asks_for_english() -> None:
    system, _ = extraction_prompt(
        ExtractableSignal(id=uuid4(), title="Choléra à Luanda", raw_text="Un article."),
        max_characters=500,
    )

    assert "English" in system


def test_the_extraction_prompt_forbids_translating_a_span() -> None:
    system, _ = extraction_prompt(
        ExtractableSignal(id=uuid4(), title="Choléra à Luanda", raw_text="Un article."),
        max_characters=500,
    )

    assert "Do not translate a span" in system


def test_the_extraction_prompt_carries_the_five_slots() -> None:
    system, _ = extraction_prompt(
        ExtractableSignal(id=uuid4(), title="Cholera in Luanda", raw_text="An article."),
        max_characters=500,
    )

    for slot in ("what_where", "counts", "timing", "spread", "reporting"):
        assert slot in system
```

Add whatever imports the file is missing: `from uuid import uuid4` and `from episignal_backend.ai.documents import ExtractableSignal`.

- [ ] **Step 2: Run them and watch two fail**

Run: `uv run pytest packages/backend/tests/test_ai_prompts.py -v -k "english or span or slots"`
Expected: the slot test passes already, because the JSON Schema names the slots; the English and span tests FAIL.

- [ ] **Step 3: Implement**

In `packages/backend/src/episignal_backend/ai/prompts.py`, replace `EXTRACTION_RULES` with:

```python
EXTRACTION_RULES = """You read one news article and return epidemiological facts as JSON.

Rules:
- Return one JSON object and nothing else. No prose, no code fence.
- Every count and every transmission flag must include source_span: a short
  phrase copied word for word from the article that states it.
- Copy every source_span in the article's own language. Do not translate a span.
- Write title_english and every brief point in English. Translate rather than
  transliterate. An article already in English keeps its own headline, with
  whitespace collapsed.
- Return exactly five brief points, one for each slot, in the order the schema
  lists them: what_where, counts, timing, spread, reporting.
- A slot the article does not address gets reported: false and one short line
  saying what is not reported. Never fill a slot from outside the article.
- If the article does not state something, return null. Never infer, never
  estimate, never carry a number over from general knowledge.
- Do not state that an outbreak is confirmed. Report what the article reports.
- Do not include any person's name, telephone number, or address.

The object must match this JSON Schema exactly:
"""
```

- [ ] **Step 4: Run the prompt tests**

Run: `uv run pytest packages/backend/tests/test_ai_prompts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/prompts.py packages/backend/tests/test_ai_prompts.py
git commit -m "feat: ask the model for an English brief and untranslated spans" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: The version, and reading what we already stored

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/schema.py`
- Test: `packages/backend/tests/test_ai_schema.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_stored_payload_tolerates_the_version_key_the_strict_model_forbids() -> None:
    stored = dict(minimal())
    stored[EXTRACTION_VERSION_KEY] = EXTRACTION_SCHEMA_VERSION

    payload = StoredExtractionPayload.model_validate(stored)

    assert payload.title_english == "Angola reports growing cholera outbreak in Luanda"
    assert len(payload.brief) == BRIEF_SLOT_COUNT


def test_a_row_written_before_this_item_is_still_readable() -> None:
    old = {
        "signal_type": "outbreak_report",
        "disease": {"name": "Cholera", "confidence": 0.97},
        "epidemiology": {"confirmed_cases": {"value": 327, "source_span": "327 confirmed cases"}},
        "confidence": 0.9,
    }

    payload = StoredExtractionPayload.model_validate(old)

    assert payload.brief == ()
    assert payload.title_english is None
    assert payload.epidemiology.confirmed_cases is not None


def test_a_stored_payload_is_an_extraction() -> None:
    assert isinstance(StoredExtractionPayload.model_validate(minimal()), Extraction)


def test_the_strict_model_still_refuses_the_version_key() -> None:
    stored = dict(minimal())
    stored[EXTRACTION_VERSION_KEY] = EXTRACTION_SCHEMA_VERSION

    with pytest.raises(ValidationError):
        Extraction.model_validate(stored)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest packages/backend/tests/test_ai_schema.py -v -k "stored or version"`
Expected: FAIL — `cannot import name 'StoredExtractionPayload'`.

- [ ] **Step 3: Implement**

At the top of `packages/backend/src/episignal_backend/ai/schema.py`, beside the other constants:

```python
# Bumped when the shape of a stored extraction changes. Version 1 is every row
# written before the brief existed: it has a `summary` and no `brief`.
EXTRACTION_SCHEMA_VERSION = 2
EXTRACTION_VERSION_KEY = "extraction_schema_version"
```

Immediately after `class Extraction`, add:

```python
class StoredExtractionPayload(Extraction):
    """A stored extraction, read back out of `signals.ai_extraction`.

    Strict on the way in, tolerant on the way back. The strict model is the
    contract with a model and must keep rejecting a missing brief; this one
    reads rows this system wrote itself, including rows written before the
    brief existed and rows carrying the version key that `Extraction` forbids.

    A version 1 row read this way has an empty brief and no English title. That
    is the honest answer — it has neither — and the backfill is what changes it.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    # Widening the parent's types is what makes an old row readable; mypy is
    # right that this is not substitutable in general, and wrong that it matters
    # here, because nothing writes through this model.
    title_english: str | None = None  # type: ignore[assignment]
    brief: tuple[BriefPoint, ...] = ()
```

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest packages/backend/tests/test_ai_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Check the types**

Run: `uv run mypy apps/api/src packages/backend/src`
Expected: `Success`. The `type: ignore[assignment]` above is required and used; do not remove it, and do not widen it to a bare `# type: ignore`.

- [ ] **Step 6: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/schema.py packages/backend/tests/test_ai_schema.py
git commit -m "feat: version the stored extraction and read old rows tolerantly" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Persistence stamps the version and writes the brief

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/repository.py:138-151`
- Test: `packages/backend/tests/test_ai_repository.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_an_accepted_extraction_stores_the_brief_as_the_signal_summary() -> None:
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

    params = session.executed[0].compile().params
    summary = next(value for value in params.values() if isinstance(value, str) and "\n" in value)
    assert summary.splitlines() == [
        "Cholera in Luanda, Angola.",
        "No case count reported.",
        "No date reported.",
        "No transmission detail reported.",
        "Reported by local media.",
    ]


def test_an_accepted_extraction_stamps_the_schema_version() -> None:
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

    params = session.executed[0].compile().params
    stored = next(value for value in params.values() if isinstance(value, dict))
    assert stored[EXTRACTION_VERSION_KEY] == EXTRACTION_SCHEMA_VERSION
    assert stored["brief"][0]["slot"] == "what_where"
```

Import `EXTRACTION_SCHEMA_VERSION` and `EXTRACTION_VERSION_KEY` from `episignal_backend.ai.schema` at the top of the test file.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest packages/backend/tests/test_ai_repository.py -v -k "brief or version"`
Expected: FAIL — `StopIteration`, because nothing writes a joined summary or a version key yet.

- [ ] **Step 3: Implement**

In `packages/backend/src/episignal_backend/ai/repository.py`, import the two constants from `episignal_backend.ai.schema` and replace `record_extraction` with:

```python
    def record_extraction(self, signal_id: UUID, stored: StoredExtraction) -> None:
        # The version is stamped here and never by the model: a version a model
        # can choose is a version that lies the moment the model is confused.
        payload = stored.extraction.model_dump(mode="json")
        payload[EXTRACTION_VERSION_KEY] = EXTRACTION_SCHEMA_VERSION

        self._session.execute(
            update(Signal)
            .where(Signal.id == signal_id)
            .values(
                processing_status=ProcessingStatus.EXTRACTED,
                ai_extraction=payload,
                ai_model=stored.model_id,
                ai_processed_at=stored.processed_at,
                disease_id=stored.disease_id,
                signal_type=stored.extraction.signal_type,
                summary="\n".join(point.text for point in stored.extraction.brief),
            )
        )
```

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest packages/backend/tests/test_ai_repository.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/repository.py packages/backend/tests/test_ai_repository.py
git commit -m "feat: store the brief and the schema version it was written under" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Matching reads stored extractions tolerantly

Without this, every row written by task 6 stops parsing in `events/repository.py`,
because the version key is an extra key and `Extraction` forbids extras. The
existing `except` there would swallow it, and matching would quietly lose the
extraction it scores with.

**Files:**
- Modify: `packages/backend/src/episignal_backend/events/repository.py:108-120`
- Test: `packages/backend/tests/test_event_repository.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_stored_extraction_survives_its_version_key() -> None:
    payload = {
        "signal_type": "outbreak_report",
        "source_language": "en",
        "title_english": "Cholera outbreak reported in Luanda",
        "brief": [
            {"slot": "what_where", "text": "Cholera in Luanda, Angola.", "reported": True},
            {"slot": "counts", "text": "327 confirmed cases.", "reported": True},
            {"slot": "timing", "text": "As of 25 August 2026.", "reported": True},
            {"slot": "spread", "text": "Acquired locally.", "reported": True},
            {"slot": "reporting", "text": "Reported by the health ministry.", "reported": True},
        ],
        "epidemiology": {"confirmed_cases": {"value": 327, "source_span": "327 confirmed cases"}},
        "confidence": 0.9,
        EXTRACTION_VERSION_KEY: EXTRACTION_SCHEMA_VERSION,
    }

    extraction = read_stored_extraction(payload)

    assert extraction is not None
    assert extraction.epidemiology.confirmed_cases is not None
    assert extraction.epidemiology.confirmed_cases.value == 327


def test_an_unreadable_extraction_is_absence_rather_than_an_exception() -> None:
    assert read_stored_extraction({"signal_type": "not_a_type"}) is None
```

Import `read_stored_extraction` from `episignal_backend.events.repository`, and the two constants from `episignal_backend.ai.schema`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest packages/backend/tests/test_event_repository.py -v -k "stored or unreadable"`
Expected: FAIL — `cannot import name 'read_stored_extraction'`.

- [ ] **Step 3: Implement**

In `packages/backend/src/episignal_backend/events/repository.py`, import `StoredExtractionPayload` from `episignal_backend.ai.schema` and `ValidationError` from `pydantic`, then add this module-level function above the class that uses it:

```python
def read_stored_extraction(payload: Any) -> Extraction | None:
    """Read `signals.ai_extraction` back, across every version we have written.

    Returns absence rather than raising: a row this system cannot parse is a row
    matching scores without an extraction, which is worse than a crash only if
    it goes unnoticed — and `processing_status` is where it is noticed.
    """
    if not isinstance(payload, dict):
        return None
    try:
        return StoredExtractionPayload.model_validate(payload)
    except ValidationError:
        return None
```

and replace the `try`/`except` block at lines 110-119 with:

```python
            extraction = read_stored_extraction(sig.ai_extraction)
```

Delete the `payload.setdefault("confidence", 0.5)` fallback with it: inventing a confidence for a row that never carried one is exactly the kind of substitution this project forbids, and `StoredExtractionPayload` no longer needs it.

- [ ] **Step 4: Run the event tests**

Run: `uv run pytest packages/backend/tests/test_event_repository.py packages/backend/tests/test_event_match.py -v`
Expected: PASS. If a test depended on the invented `0.5` confidence, change the test's payload to state a confidence rather than restoring the fallback.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/events/repository.py packages/backend/tests/test_event_repository.py
git commit -m "fix: read stored extractions through the tolerant model" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: The backfill selection

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/protocol.py:44`
- Modify: `packages/backend/src/episignal_backend/ai/repository.py`
- Test: `packages/backend/tests/test_ai_repository.py`
- Test: `packages/backend/tests/test_ai_protocol.py`

- [ ] **Step 1: Write the failing tests**

In `packages/backend/tests/test_ai_repository.py`:

```python
def test_the_backfill_selects_only_extractions_below_the_current_version() -> None:
    session = FakeSession([FakeResult([])])

    SqlAlchemyAiRepository(session).awaiting_backfill(limit=10)

    statement = str(session.executed[0])
    assert "processing_status IN" in statement
    assert "ai_extraction IS NOT NULL" in statement
    assert "raw_text IS NOT NULL" in statement


def test_the_backfill_never_selects_a_signal_awaiting_a_human() -> None:
    session = FakeSession([FakeResult([])])

    SqlAlchemyAiRepository(session).awaiting_backfill(limit=10)

    compiled = session.executed[0].compile()
    selected = [value for value in compiled.params.values() if isinstance(value, str)]
    assert ProcessingStatus.NEEDS_REVIEW.value not in selected
    assert ProcessingStatus.NORMALIZED.value not in selected
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest packages/backend/tests/test_ai_repository.py -v -k backfill`
Expected: FAIL — `AttributeError: 'SqlAlchemyAiRepository' object has no attribute 'awaiting_backfill'`.

- [ ] **Step 3: Implement**

In `packages/backend/src/episignal_backend/ai/protocol.py`, add to `AiRepository`, directly under `awaiting_extraction`:

```python
    def awaiting_backfill(self, *, limit: int) -> Sequence[ExtractableSignal]: ...
```

In `packages/backend/src/episignal_backend/ai/repository.py`, add after `awaiting_extraction`:

```python
    def awaiting_backfill(self, *, limit: int) -> Sequence[ExtractableSignal]:
        """Signals whose stored extraction predates the current schema.

        `needs_review` and `normalized` are not selectable here for the same
        reason they are not selectable for extraction: one is owed a human
        decision, and the other has not been classified yet.
        """
        stored_version = Signal.ai_extraction[EXTRACTION_VERSION_KEY].as_integer()
        rows = self._session.execute(
            select(Signal)
            .where(
                Signal.processing_status.in_(
                    (
                        ProcessingStatus.EXTRACTED,
                        ProcessingStatus.GEOCODED,
                        ProcessingStatus.MATCHED,
                        ProcessingStatus.PUBLISHED,
                    )
                ),
                Signal.ai_extraction.is_not(None),
                Signal.raw_text.is_not(None),
                or_(stored_version.is_(None), stored_version < EXTRACTION_SCHEMA_VERSION),
            )
            .order_by(Signal.first_seen_at)
            .limit(limit)
        ).scalars()
        return tuple(
            ExtractableSignal(id=row.id, title=row.title, raw_text=row.raw_text or "")
            for row in rows
        )
```

- [ ] **Step 4: Run the tests and the type check**

Run: `uv run pytest packages/backend/tests/test_ai_repository.py packages/backend/tests/test_ai_protocol.py -v`
Expected: PASS.

Run: `uv run mypy apps/api/src packages/backend/src`
Expected: `Success`. If mypy objects to indexing the JSONB column, add a narrow ignore on that line only, in the style of `packages/backend/src/episignal_backend/ai/repository.py:97`.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai packages/backend/tests/test_ai_repository.py packages/backend/tests/test_ai_protocol.py
git commit -m "feat: select extractions that predate the current schema" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: The backfill pass

`run_backfill` differs from `run_extraction` in exactly one thing: which
signals it works on. Share the rest rather than copying it.

**Files:**
- Modify: `packages/backend/src/episignal_backend/ai/extract.py:65-140`
- Test: `packages/backend/tests/test_ai_extract.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_backfill_re_extracts_a_stale_signal() -> None:
    signal = ExtractableSignal(id=FIRST, title="Cholera in Luanda", raw_text=BODY)
    repository = BackfillRepository([signal])
    model = ScriptedModel([GOOD])

    result = run_backfill(repository, model, guards=guards(), now=lambda: NOW)

    assert result.examined == 1
    assert result.extracted == 1
    assert FIRST in repository.stored


def test_the_backfill_asks_for_stale_work_and_never_for_new_work() -> None:
    repository = BackfillRepository([])
    model = ScriptedModel([])

    run_backfill(repository, model, guards=guards(), now=lambda: NOW)

    assert repository.asked_for_backfill is True


def test_a_rejected_re_extraction_leaves_the_row_exactly_where_it_was() -> None:
    signal = ExtractableSignal(id=FIRST, title="Cholera in Luanda", raw_text=BODY)
    repository = BackfillRepository([signal])
    model = ScriptedModel([UNGROUNDED, UNGROUNDED, UNGROUNDED])

    result = run_backfill(repository, model, guards=guards(), now=lambda: NOW)

    assert result.extracted == 0
    assert FIRST not in repository.stored


def test_a_rejected_first_extraction_still_goes_to_review() -> None:
    signal = ExtractableSignal(id=SECOND, title="Cholera in Luanda", raw_text=BODY)
    repository = ExtractRepository([signal])
    model = ScriptedModel([UNGROUNDED, UNGROUNDED, UNGROUNDED])

    result = run_extraction(repository, model, guards=guards(), now=lambda: NOW)

    assert result.reviewed == 1
```

with this fake beside `ExtractRepository` in the same file. Its `mark_needs_review`
is the assertion that matters: a re-extraction that fails must not move a matched
signal into a human queue, because the answer it already had is still good.

```python
class BackfillRepository(ExtractRepository):
    def __init__(self, stale: Sequence[ExtractableSignal]) -> None:
        super().__init__(())
        self._stale = tuple(stale)
        self.asked_for_backfill = False

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        raise AssertionError("the backfill must not select new work")

    def awaiting_backfill(self, *, limit: int) -> Sequence[ExtractableSignal]:
        self.asked_for_backfill = True
        return self._stale[:limit]

    def mark_needs_review(self, signal_id: UUID) -> None:
        raise AssertionError("a rejected re-extraction must leave the row where it is")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest packages/backend/tests/test_ai_extract.py -v -k backfill`
Expected: FAIL — `cannot import name 'run_backfill'`.

- [ ] **Step 3: Implement**

In `packages/backend/src/episignal_backend/ai/extract.py`, rename `run_extraction` to `_run_pass`, give it a `pending: Sequence[ExtractableSignal]` parameter in place of its `limit` parameter, and delete the `pending = repository.awaiting_extraction(limit=limit)` line from its body. Add `from collections.abc import Callable, Sequence` to the imports.

Give `_run_pass` one more keyword-only parameter, `demote_on_rejection: bool`, and use it at the one place the two passes differ in behaviour:

```python
            elif result.outcome is ClimbOutcome.REJECTED:
                # A first extraction that cannot be trusted owes a human a look.
                # A re-extraction that cannot be trusted owes nobody anything:
                # the row already holds an answer that passed these same checks,
                # and demoting it would throw that away to record a failure.
                if demote_on_rejection:
                    repository.mark_needs_review(signal.id)
                reviewed += 1
```

Then add the two public entry points:

```python
def run_extraction(
    repository: AiRepository,
    model: ChatModel,
    *,
    guards: Guards,
    limit: int = DEFAULT_LIMIT,
    max_tier: int = DEFAULT_MAX_TIER,
    max_input_characters: int = DEFAULT_MAX_INPUT_CHARACTERS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ExtractionResult:
    """Extract from signals nobody has extracted from yet."""
    return _run_pass(
        repository,
        model,
        repository.awaiting_extraction(limit=limit),
        guards=guards,
        demote_on_rejection=True,
        max_tier=max_tier,
        max_input_characters=max_input_characters,
        min_confidence=min_confidence,
        now=now,
    )


def run_backfill(
    repository: AiRepository,
    model: ChatModel,
    *,
    guards: Guards,
    limit: int = DEFAULT_LIMIT,
    max_tier: int = DEFAULT_MAX_TIER,
    max_input_characters: int = DEFAULT_MAX_INPUT_CHARACTERS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ExtractionResult:
    """Re-extract signals whose stored extraction predates the current schema.

    Identical to the extraction pass in every respect but its selection, which
    is why it shares that pass rather than copying it. A rejected answer leaves
    the existing extraction untouched: a backfill never destroys a good old
    answer in order to store a bad new one.
    """
    return _run_pass(
        repository,
        model,
        repository.awaiting_backfill(limit=limit),
        guards=guards,
        demote_on_rejection=False,
        max_tier=max_tier,
        max_input_characters=max_input_characters,
        min_confidence=min_confidence,
        now=now,
    )
```

- [ ] **Step 4: Run the extraction tests**

Run: `uv run pytest packages/backend/tests/test_ai_extract.py -v`
Expected: PASS, including every pre-existing `run_extraction` test unchanged.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/ai/extract.py packages/backend/tests/test_ai_extract.py
git commit -m "feat: add the backfill pass over stale extractions" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: The backfill runner

**Files:**
- Create: `packages/backend/src/episignal_backend/backfill_runner.py`
- Create: `packages/backend/tests/test_backfill_runner.py`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from episignal_backend.ai.extract import ExtractionResult
from episignal_backend.backfill_runner import Arguments, main, parse_arguments


def _result() -> ExtractionResult:
    return ExtractionResult(examined=3, extracted=3, reviewed=0, unavailable=0, requests=3)


def test_the_limit_defaults_to_the_configured_batch() -> None:
    assert parse_arguments([]) == Arguments(limit=None)


def test_a_limit_can_be_given() -> None:
    assert parse_arguments(["--limit", "5"]).limit == 5


def test_the_pnpm_double_dash_separator_is_ignored() -> None:
    assert parse_arguments(["--", "--limit", "5"]).limit == 5


def test_a_successful_run_prints_counts_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("episignal_backend.backfill_runner._run", lambda arguments: _result())

    assert main([]) == 0

    output = capsys.readouterr().out
    assert "examined=3" in output
    assert "re_extracted=3" in output


def test_a_failing_run_never_prints_a_body_or_a_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(arguments: Arguments) -> None:
        raise RuntimeError("sk-secret-value leaked into an exception")

    monkeypatch.setattr("episignal_backend.backfill_runner._run", explode)

    assert main([]) == 1
    captured = capsys.readouterr()
    assert "sk-secret-value" not in captured.err
    assert "sk-secret-value" not in captured.out
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest packages/backend/tests/test_backfill_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'episignal_backend.backfill_runner'`.

- [ ] **Step 3: Implement**

Create `packages/backend/src/episignal_backend/backfill_runner.py`:

```python
"""Entry point for `pnpm extract:backfill`.

Re-extracts signals whose stored extraction predates the current schema, so that
rows written before the brief existed can be brought up to it. Deliberately not
part of the daily chain: a prompt change must never be able to silently re-spend
the budget across a whole corpus.

Counts only. The API key, the prompts, and the article bodies never reach stdout
or stderr, the same posture as `extract_runner.py`.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.ai.extract import ExtractionResult, run_backfill
from episignal_backend.ai.ladder import Guards
from episignal_backend.ai.openrouter import OpenRouterChatModel
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope


@dataclass(frozen=True)
class Arguments:
    limit: int | None


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="backfill",
        description="Re-extract signals whose stored extraction predates the current schema.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Signals to re-extract. Defaults to EPISIGNAL_AI_SIGNAL_BATCH_LIMIT.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(limit=parsed.limit)


def _run(arguments: Arguments) -> ExtractionResult:
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

    with session_scope() as session:
        return run_backfill(
            SqlAlchemyAiRepository(session),
            model,
            guards=guards,
            limit=arguments.limit or settings.ai_signal_batch_limit,
            max_tier=settings.ai_max_tier,
            max_input_characters=settings.ai_max_input_characters,
            min_confidence=settings.ai_min_confidence,
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        result = _run(arguments)
    except Exception as error:
        # Fixed text plus the exception's type, never its payload: an exception
        # raised near a prompt can carry the article, and one raised near the
        # client can carry the key.
        print(
            f"Backfill failed before completing ({type(error).__name__}). "
            "Check the database and EPISIGNAL_OPENROUTER_API_KEY.",
            file=sys.stderr,
        )
        return 1

    # `rejected`, not `review`: a re-extraction this system would not trust
    # leaves the row exactly where it was, holding the answer it already had.
    print(
        f"examined={result.examined} re_extracted={result.extracted} "
        f"rejected={result.reviewed} unavailable={result.unavailable} "
        f"requests={result.requests} stopped_early={result.stopped_early}"
    )
    return 0 if result.reviewed == 0 and result.unavailable == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest packages/backend/tests/test_backfill_runner.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add packages/backend/src/episignal_backend/backfill_runner.py packages/backend/tests/test_backfill_runner.py
git commit -m "feat: add the backfill runner" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: The command and the environment

**Files:**
- Modify: `package.json`
- Modify: `apps/api/.env.example`

- [ ] **Step 1: Add the script**

In `package.json`, directly after the `extract:signals` line:

```json
    "extract:backfill": "uv run --package episignal-backend python -m episignal_backend.backfill_runner",
```

- [ ] **Step 2: Prove it is wired**

Run: `corepack pnpm extract:backfill -- --help`
Expected: argparse usage text naming `--limit`. It must not reach the database, because `--help` exits first.

- [ ] **Step 3: Document the key**

In `apps/api/.env.example`, above the scheduler block, add:

```text
# The AI stages refuse to run without this. No value here on purpose: put the
# real key in apps/api/.env, which is not committed.
EPISIGNAL_OPENROUTER_API_KEY=
```

- [ ] **Step 4: Commit**

```bash
git add package.json apps/api/.env.example
git commit -m "chore: wire extract:backfill and document the OpenRouter key" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: The naming authority

**Files:**
- Modify: `CONTEXT.md`

- [ ] **Step 1: Add the three terms**

In `CONTEXT.md`, in the **Judgement** section, directly after the **Extraction** entry:

```markdown
**Brief**:
The five-bullet English summary of a signal, written to be scanned. One brief per
signal, always five bullets, always in the same order.
_Avoid_: summary, abstract, digest.

**Slot**:
One of the five fixed questions a brief answers, identified by name and fixed in
position. A slot is a position in a brief, never a rung of the model ladder,
which is a *tier*, and never a step of the pipeline, which is a *stage*.
_Avoid_: section, field, bullet.

**English title**:
The article's own headline rendered in English. Stored beside the publisher's
headline, never over it.
_Avoid_: translated title, headline.
```

- [ ] **Step 2: Commit**

```bash
git add CONTEXT.md
git commit -m "docs: name the brief, the slot, and the English title" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: Live verification and the completion report

This is the only task that spends money and the only one that touches the
database. Everything above runs offline.

**Files:**
- Create: `docs/reports/2026-08-28-subproject-c2-report.md`
- Modify: `STATUS.md` (task ledger ticks and the verified baseline only)

- [ ] **Step 1: Run the gate**

Run: `corepack pnpm verify`
Expected: exit code 0. Keep the whole output — the report quotes the real test counts, not a claim that tests passed.

- [ ] **Step 2: Confirm the database is reachable**

Run: `corepack pnpm db:check`
Expected: `missing_tables: []` and PostGIS up. No migration was added by this item, so nothing should have changed here.

- [ ] **Step 3: Extract something new, in English**

Run: `corepack pnpm extract:signals -- --limit 5`
Expected: a counts-only line. Then confirm one row carries a brief:

```bash
uv run --package episignal-backend python -c "
from sqlalchemy import text
from episignal_backend.db.session import session_scope
with session_scope() as session:
    row = session.execute(text(
        \"SELECT ai_extraction->>'title_english', ai_extraction->>'extraction_schema_version', \"
        \"jsonb_array_length(ai_extraction->'brief'), left(summary, 120) \"
        \"FROM signals WHERE ai_extraction ? 'brief' ORDER BY ai_processed_at DESC LIMIT 1\"
    )).first()
    print(row)
"
```

Expected: a title, version `2`, a brief length of `5`, and a summary whose first line is the `what_where` bullet.

- [ ] **Step 4: Backfill the old rows**

Run: `corepack pnpm extract:backfill -- --limit 10`
Expected: `examined=` above zero on the first run, `examined=0` on an immediate second run, because every selected row is now at the current version.

- [ ] **Step 5: Write the report**

Create `docs/reports/2026-08-28-subproject-c2-report.md` following
`docs/reports/2026-08-28-subproject-l-report.md`. It must contain, untruncated:

- the full `corepack pnpm verify` output including the test counts;
- the `db:check` JSON;
- the `extract:signals` line and the row printed in step 3;
- both `extract:backfill` lines, the second showing `examined=0`;
- the commit the run was performed at.

- [ ] **Step 6: Update STATUS.md**

Tick every task in the ledger, and update the **Verified baseline** table with
the counts from step 1 and the commit you ran at. Those two sections belong to
the worker. Do not set `C2` to `verified` in `ROADMAP.md` — the planner does
that, after reading the report.

- [ ] **Step 7: Commit and hand back**

```bash
git add docs/reports/2026-08-28-subproject-c2-report.md STATUS.md
git commit -m "docs: sub-project C2 completion report" -m "Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

Then report to the planner: what ran, what it printed, and anything in the spec
you found to be wrong. A worker that finds the plan wrong stops and reports
rather than improvising a different design.

---

## Notes on things that will surprise you

**The brief is not a place to be helpful.** Bullet 2 on an article with no
numbers says *No case count reported.* It does not say what the disease usually
does, what a previous outbreak reached, or what the model believes. Every review
of this item will check that first.

**Spans stay foreign.** The French fixture in `test_ai_extract.py` is the case
this item exists for: an English brief above French spans. If you find yourself
translating a `source_span` to make grounding pass, you have inverted the
design — grounding is what proves the span was really in the article.

**Old rows are readable, not pretty.** Between task 5 and the backfill in task
13, a version 1 row has an empty brief. That is correct. Do not add a fallback
that renders its old `summary` as a fake bullet.
