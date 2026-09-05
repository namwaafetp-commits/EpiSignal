"""Prompt boundary tests for the three active model purposes."""

from datetime import UTC, datetime
from uuid import uuid4

from episignal_backend.ai.documents import ClassifiableSignal, ExtractableSignal
from episignal_backend.ai.prompts import (
    GEMINI_EXTRACTION_PROMPT,
    IDENTITY_REPAIR,
    classification_prompt,
    extraction_prompt,
    truncate,
)


def test_classification_prompt_contains_only_discovery_metadata() -> None:
    signal = ClassifiableSignal(
        id=uuid4(),
        title="Cholera cases rise",
        excerpt="Officials reported new cases.",
        source_name="WHO",
        published_at=datetime(2026, 9, 2, tzinfo=UTC),
    )
    system, user = classification_prompt(signal)
    assert "TITLE" in user and "SNIPPET" in user and "SOURCE" in user and "PUBLISHED_AT" in user
    assert "disease" not in user.lower() and "location" not in user.lower()
    assert "relevant" in system and "confidence" in system


def test_extraction_prompt_uses_clean_article_and_exact_identity_repair() -> None:
    signal = ExtractableSignal(id=uuid4(), title="Measles in Cebu", raw_text="A report from Cebu.")
    system, user = extraction_prompt(signal, max_characters=1000)
    assert system == GEMINI_EXTRACTION_PROMPT.replace("<title>", signal.title).replace(
        "<clean article body>", signal.raw_text
    )
    assert user == "Return the extraction JSON."
    assert "disease" in system and "locations" in system
    assert "cases" not in system.lower()
    assert IDENTITY_REPAIR


def test_truncation_stops_at_a_whitespace_boundary() -> None:
    assert truncate("one two three", 7) == "one"


def test_truncation_of_text_with_no_whitespace_still_bounds_the_length() -> None:
    assert len(truncate("x" * 20, 7)) <= 7
