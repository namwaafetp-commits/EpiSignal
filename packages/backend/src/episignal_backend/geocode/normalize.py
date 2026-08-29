"""Name forms and country alias resolution.

Two forms, never merged. The `normalized` form is what a name looks like with
its case, spacing, and punctuation made uniform; the `ascii` form is that with
its diacritics folded away. Folding is useful and lossy at the same time: it
matches Krakow to Kraków, and it also collides names that were distinct, which
is why an exact match is always tried first and a folded match is scored lower.
"""

import unicodedata
from collections.abc import Mapping


def normalized_form(value: str) -> str:
    """Casefold, replace punctuation with a separator, collapse whitespace."""
    separated = "".join(
        " " if unicodedata.category(character).startswith(("P", "S")) else character
        for character in value
    )
    return " ".join(separated.casefold().split())


def ascii_form(value: str) -> str:
    """The normalized form with combining marks removed."""
    decomposed = unicodedata.normalize("NFKD", normalized_form(value))
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def cache_key(value: str) -> str:
    """Whitespace-collapsed lower case: the key the external cache is stored under.

    Deliberately cruder than `normalized_form`, and never used for gazetteer
    matching. The cache is written and read by the same code, so it only needs
    to be deterministic, and the plain lower case matches how `resolve_disease`
    keys its vocabulary lookups.
    """
    return " ".join(value.split()).lower()


def resolve_country(name: str | None, aliases: Mapping[str, str]) -> str | None:
    """Map an extracted country name to an ISO-3166 alpha-2 code.

    Exact match against the normalized form, never fuzzy. A country that fails
    to resolve is a seed row someone adds; a fuzzy match is Niger silently
    becoming Nigeria, which is the error this whole sub-project is shaped to
    avoid.
    """
    if name is None:
        return None
    return aliases.get(normalized_form(name))
