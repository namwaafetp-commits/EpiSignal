import json
from uuid import UUID, uuid4

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
