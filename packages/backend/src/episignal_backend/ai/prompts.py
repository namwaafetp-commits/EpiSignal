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

GEMINI_EXTRACTION_PROMPT = """You extract the main disease and event locations from one news
article.
Read both TITLE and ARTICLE.
Return JSON only.
Extract only:
1. disease
2. locations
DISEASE
Return the main disease or pathogen being reported.
Use a sensible natural disease name.
Examples:
- measles
- dengue
- Nipah virus infection
- H5N1 avian influenza
- Salmonella Enteritidis
Do not invent a disease.
The disease does not need to match a predefined vocabulary.
LOCATION
Return locations where the reported disease or public-health event actually occurs.
Each location contains:
- town
- country
"town" means the most specific useful local event location available.
It may therefore be a:
- town
- city
- county
- district
- local region
Examples:
- Cebu
- Cortland County
- Frankfurt
- Kozhikode district
- Lancaster County
If no useful local location is reported, town may be null.
Multiple event locations are allowed.
Reliable general geographic knowledge may be used to resolve an explicitly named place to its
containing country.
Examples:
Cebu → Philippines
North Carolina → United States
NSW → Australia
Dhaka → Bangladesh
Do not infer event location from:
- publisher location
- publisher name
- website domain
- author location
- organization headquarters
- unrelated background geography
Return only locations actually relevant to the reported event.
If disease cannot be identified, return null.
If event location cannot be identified, return an empty locations array.
Return exactly:
{
  "disease": string | null,
  "locations": [
    {
      "town": string | null,
      "country": string | null
    }
  ]
}

Input:

TITLE:
<title>
ARTICLE:
<clean article body>"""

IDENTITY_REPAIR = """IDENTITY REPAIR
The previous extraction omitted the disease and/or event country.
Re-read TITLE first, then ARTICLE.
TITLE is evidence.
If disease or event geography is explicitly reported, populate it.
Reliable geographic knowledge may resolve an explicitly named place to its country.
Do not infer publisher or organization location.
Return the complete extraction JSON."""

CLASSIFICATION_RULES = """You decide whether one news item is relevant to infectious-disease
public health.

Rules:
- Return one JSON object and nothing else. No prose, no code fence.
- Return only relevance, confidence, and an optional short reason_code.
- Do not identify disease, location, cases, deaths, or event type in this pass.
- Relevant includes infectious-disease outbreaks or cases, surveillance,
  emerging infections, zoonoses, vaccination or immunisation, vaccine safety,
  infectious-disease prevention or control, outbreak response,
  infectious-disease public-health programmes, and important
  infectious-disease public-health system issues.
- When you are unsure, mark it relevant: a missed outbreak costs more than a
  wasted extraction.

The object must match this JSON Schema exactly:
"""

TRIAGE_RULES = """You are classifying one infectious-disease/public-health news item.

Rules:
- Return one JSON object and nothing else. No prose, no code fence.
- Use TITLE and ARTICLE CONTENT as evidence.
- Decide relevance, identify the disease being reported, and identify where the
  reported event actually occurred in the supplied content.
- TITLE counts as evidence. ARTICLE CONTENT counts as evidence.
- country must be a two-letter ISO 3166-1 alpha-2 code, or null when uncertain.
- admin1 is the first-level administrative region explicitly stated or clearly
  supported by the supplied content, or null when uncertain.
- location_text is the event location as reported in the supplied content.
- Identify the event location, not every location mentioned in the article.
- Ignore unrelated comparisons, related-story text, navigation, advertisements,
  and boilerplate.
- Do not infer location from the publisher or organization name. FDA, CDC, WHO,
  HHS, NCDC, and similar organizations are not event-location evidence.
- Every field you are not certain of from the supplied TITLE or ARTICLE CONTENT
  must be null. Prefer null over an unsupported guess.
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
    system = GEMINI_EXTRACTION_PROMPT.replace("<title>", signal.title).replace(
        "<clean article body>", truncate(signal.raw_text, max_characters)
    )
    return system, "Return the extraction JSON."


def identity_repair_prompt(signal: ExtractableSignal, *, max_characters: int) -> tuple[str, str]:
    system, user = extraction_prompt(signal, max_characters=max_characters)
    return system + "\n\n" + IDENTITY_REPAIR, user


CLASSIFICATION_SNIPPET_CHARACTERS = 400


def classification_prompt(signal: ClassifiableSignal) -> tuple[str, str]:
    """Build the cheap relevance request from discovery metadata only."""
    system = CLASSIFICATION_RULES + json.dumps(classification_json_schema(), sort_keys=True)
    item = "\n".join(
        (
            f"TITLE: {signal.title}",
            f"SNIPPET: {truncate(signal.excerpt, CLASSIFICATION_SNIPPET_CHARACTERS)}",
            f"SOURCE: {signal.source_name}",
            "PUBLISHED_AT: "
            f"{signal.published_at.isoformat() if signal.published_at else 'unknown'}",
        )
    )
    return system, item


def triage_prompt(signal: TriageableSignal, *, max_characters: int) -> tuple[str, str]:
    system = TRIAGE_RULES + json.dumps(triage_json_schema(), sort_keys=True)
    published = signal.published_at.isoformat() if signal.published_at else "unknown"
    user = (
        f"TITLE: {signal.title}\n"
        f"SOURCE: {signal.source_name}\n"
        f"PUBLISHED: {published}\n"
        f"URL: {signal.url}\n"
        f"LANGUAGE: {signal.language or 'unknown'}\n\n"
        f"ARTICLE CONTENT:\n{truncate(signal.article_content, max_characters)}"
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
- Extract concrete response_actions and driver_or_barrier_evidence from any
  member that reports them. Each item must contain concise English text, a
  verbatim source_span, and source_index. Return an empty list when absent.
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
