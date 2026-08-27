"""Stage 0, gate two: how alike two stored documents are.

Deterministic and explainable on purpose. Embeddings would answer the same
question with a model call, and this stage exists to run before any model call.
Exact set arithmetic rather than MinHash or SimHash: the candidate window holds
at most low thousands of rows, so an approximation would save nothing and would
make "why were these two merged" harder to answer.

This module imports neither SQLAlchemy nor httpx.
"""

import re
import unicodedata

# A spaced dash, in any of the three widths a publisher might use.
SEPARATOR = re.compile(r"\s[-–—]\s")
PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)

# Publisher furniture is short: "Telemundo New York ( 47 )" is six tokens. A
# longer tail is part of the headline, as in "How a near - fatal illness
# inspired a Highlander musical voyage", and truncating it would throw away most
# of the title.
FURNITURE_MAX_WORDS = 6


def drop_furniture(title: str) -> str:
    matches = list(SEPARATOR.finditer(title))
    if not matches:
        return title

    last = matches[-1]
    tail = title[last.end() :]
    if len(tail.split()) > FURNITURE_MAX_WORDS:
        return title
    return title[: last.start()]


def normalize_title(title: str) -> frozenset[str]:
    folded = unicodedata.normalize("NFC", title).casefold()
    stripped = PUNCTUATION.sub(" ", drop_furniture(folded))
    return frozenset(stripped.split())


def shingles(body: str, size: int) -> frozenset[str]:
    words = unicodedata.normalize("NFC", body).casefold().split()
    if not words:
        return frozenset()
    if len(words) < size:
        # Too short to shingle. Comparing it whole is honest; padding it would
        # invent overlap that the text does not have.
        return frozenset({" ".join(words)})
    return frozenset(
        " ".join(words[index : index + size]) for index in range(len(words) - size + 1)
    )


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    # Two empty sets are not a perfect match. Nothing in common with nothing is
    # no evidence of syndication, and returning 1.0 would merge every stub.
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def title_similarity(left: str, right: str) -> float:
    return jaccard(normalize_title(left), normalize_title(right))


def body_similarity(left: str, right: str, *, size: int) -> float:
    return jaccard(shingles(left, size), shingles(right, size))
