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
