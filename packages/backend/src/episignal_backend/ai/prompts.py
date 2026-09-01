"""Prompt construction, generated from the schemas that validate the answers.

Written as data, not as f-strings scattered through the passes, so that the
benchmarking harness in sub-project F can compare models against a prompt that
is known to be identical between runs.

This module imports neither SQLAlchemy nor httpx.
"""

import json
from collections.abc import Sequence

from episignal_backend.ai.documents import (
    ClassifiableSignal,
    ClusterMemberSignal,
    ExtractableSignal,
    TriageableSignal,
)
from episignal_backend.ai.schema import (
    classification_json_schema,
    extraction_json_schema,
    triage_json_schema,
)

EXTRACTION_RULES = """You read one news article and return epidemiological facts as JSON.

Rules:
- Return one JSON object and nothing else. No prose, no code fence.
- Every count and every transmission flag must include source_span: a short
  phrase copied word for word from the article that states it.
- TITLE and ARTICLE are both supplied evidence. An entity explicitly written in
  TITLE counts as reported evidence; do not return null for a disease, country,
  or province explicitly named in TITLE or ARTICLE.
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

CLASSIFICATION_RULES = """You decide whether each news item concerns a public health event.

Rules:
- Return one JSON object and nothing else. No prose, no code fence.
- Return exactly one result for every id you are given, and no other id.
- Copy each id back character for character.
- When you are unsure, mark it relevant: a missed outbreak costs more than a
  wasted extraction.

The object must match this JSON Schema exactly:
"""

TRIAGE_RULES = """You read one news item and return structured metadata as JSON.

Rules:
- Return one JSON object and nothing else. No prose, no code fence.
- TITLE and SNIPPET are both supplied evidence. An entity explicitly written in
  TITLE counts as reported evidence; do not return null for a disease, country,
  or province explicitly named in TITLE or SNIPPET.
- Every field you are not certain of from the supplied TITLE or SNIPPET must be null.
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


def classification_prompt(batch: Sequence[ClassifiableSignal]) -> tuple[str, str]:
    """The title-only relevance gate.

    The operator's call: relevance is decided from the headline alone, so an
    irrelevant item leaves the funnel for the cost of a few tokens. Recall is
    protected by the unsure-means-relevant rule above, and a headline that
    hides a relevant story is caught one stage later by the full-text
    extraction pass -- never by a guess at what the article might contain.
    """
    system = CLASSIFICATION_RULES + json.dumps(classification_json_schema(), sort_keys=True)
    items = "\n\n".join(f"id: {signal.id}\ntitle: {signal.title}" for signal in batch)
    return system, items


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
    """One repair carrying the validation failure the model must correct."""
    system, user = triage_prompt(signal, max_characters=max_characters)
    return system, user + "\n\n" + TRIAGE_REPAIR.format(error=error)


MAX_CLUSTER_MEMBERS = 4
CLUSTER_MEMBER_CHARACTERS = 4000

CLUSTER_EXTRACTION_RULES = """You read several news articles about the SAME event
and return one set of epidemiological facts as JSON.

Rules:
- Return one JSON object and nothing else. No prose, no code fence.
- The articles are numbered. Each begins with a line reading SOURCE n.
- Every count and every transmission flag must include source_index: the number
  of the single article you read it from, and source_span: a short phrase
  copied word for word from THAT article.
- Never combine two articles into one number. If they disagree, report the
  figure from the article you judge most authoritative and cite that article.
- Copy every source_span in its own article's language. Do not translate a span.
- Write title_english and every brief point in English. Translate rather than
  transliterate.
- Return exactly five brief points, one for each slot, in the order the schema
  lists them: what_where, counts, timing, spread, reporting.
- A slot no article addresses gets reported: false and one short line saying
  what is not reported. Never fill a slot from outside the articles.
- If no article states something, return null. Never infer, never estimate,
  never carry a number over from general knowledge.
- Do not state that an outbreak is confirmed. Report what the articles report.
- Do not include any person's name, telephone number, or address.

The object must match this JSON Schema exactly:
"""


def cluster_extraction_prompt(
    members: Sequence[ClusterMemberSignal], *, max_characters: int
) -> tuple[str, str]:
    """One request for one story, with every member kept separately addressable.

    The members are laid out with their index in the text rather than only in
    the schema, because the model has to cite an index it can see.
    """
    system = CLUSTER_EXTRACTION_RULES + json.dumps(extraction_json_schema(), sort_keys=True)
    blocks = [
        f"SOURCE {member.source_index}\nTITLE: {member.title}\n"
        f"ARTICLE:\n{truncate(member.raw_text, max_characters)}"
        for member in members
    ]
    return system, "\n\n---\n\n".join(blocks)
