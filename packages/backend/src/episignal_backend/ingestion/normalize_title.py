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
