"""The second-pass disease classifier.

The extraction pass resolves a disease name by exact match against the
reviewed vocabulary and nothing else, because a fuzzy match is how a measles
report becomes a cholera event. A miss is honest but not final: this pass asks
a smarter model to choose from the same reviewed candidates, with an explicit
licence to answer null. The model can only narrow the vocabulary's own answer,
never widen it -- a slug is accepted only when the candidate list already held
it, and the caller resolves the stored link from the vocabulary, not from
anything the model said.

This module imports neither SQLAlchemy nor httpx.
"""

import json
import logging
from collections.abc import Sequence

from episignal_backend.ai.documents import ChatRequest, DiseaseCandidate, ModelSpec
from episignal_backend.ai.protocol import ChatModel

logger = logging.getLogger("episignal_backend.ai.classify_disease")

__all__ = ["DiseaseCandidate", "classify_disease", "disease_classify_prompt"]


CLASSIFY_SYSTEM = (
    "You are a medical taxonomy classifier. "
    "Answer ONLY with JSON: one JSON object, no prose, no code fence."
)


def disease_classify_prompt(name: str, candidates: Sequence[DiseaseCandidate]) -> tuple[str, str]:
    system = CLASSIFY_SYSTEM
    listing = "\n".join(
        f"- slug: {candidate.slug} | name: {candidate.canonical_name} | synonyms: "
        + (", ".join(candidate.synonyms) if candidate.synonyms else "(none)")
        for candidate in candidates
    )
    user = (
        f"Disease name as written in the article: {name}\n\n"
        "Candidate diseases:\n"
        f"{listing}\n\n"
        "Choose the one candidate this name refers to and copy its slug exactly. "
        "Choose only from these candidates; never invent a slug, a name, or a synonym. "
        "Returning null is the correct answer when no candidate matches: "
        "a wrong match is worse than no match. "
        'Answer with exactly this JSON shape: {"slug": "<slug or null>"}'
    )
    return system, user


def classify_disease(
    model: ChatModel,
    spec: ModelSpec,
    name: str,
    candidates: Sequence[DiseaseCandidate],
) -> str | None:
    """One request, one answer: a candidate's slug, or None.

    Every failure mode -- the provider, the JSON, a slug outside the candidate
    set -- is the same answer as an honest null, because the caller's next step
    (leave the disease unlinked) is identical for all of them.
    """
    system, user = disease_classify_prompt(name, candidates)
    request = ChatRequest(model_id=spec.model_id, system=system, user=user)
    try:
        response = model.complete(request)
        parsed = json.loads(response.content)
    except Exception as error:
        logger.info("Disease classification did not answer (%s)", type(error).__name__)
        return None
    if not isinstance(parsed, dict):
        return None
    slug = parsed.get("slug")
    known = {candidate.slug for candidate in candidates}
    if isinstance(slug, str) and slug in known:
        return slug
    return None
