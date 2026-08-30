"""Content fingerprinting.

The hash decides whether a retrieved document is a new version of one already
stored, so it must ignore reformatting and react to any change in wording or in
a reported number. The digest is 64 hex characters, exactly the width of
`signals.content_hash`.
"""

import hashlib
import unicodedata

SEPARATOR = "\x1f"


def _collapse(value: str) -> str:
    # NFC first: the same place name can arrive precomposed or decomposed, and a
    # re-encoded diacritic is not a change in what the document says.
    return " ".join(unicodedata.normalize("NFC", value).split())


def content_hash(title: str, body: str) -> str:
    payload = f"{_collapse(title)}{SEPARATOR}{_collapse(body)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_content_hash(title: str, body: str | None, stored_hash: str | None) -> bool:
    """Verify that a stored content hash matches the recomputed hash of (title, body).

    Returns True if stored_hash is a non-empty string matching content_hash(title, body or "").
    """
    if not stored_hash or not isinstance(stored_hash, str):
        return False
    return content_hash(title, body or "") == stored_hash
