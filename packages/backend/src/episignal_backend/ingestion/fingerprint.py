"""Content fingerprinting.

The hash decides whether a retrieved document is a new version of one already
stored, so it must ignore reformatting and react to any change in wording or in
a reported number. The digest is 64 hex characters, exactly the width of
`signals.content_hash`.
"""

import hashlib

SEPARATOR = "\x1f"


def _collapse(value: str) -> str:
    return " ".join(value.split())


def content_hash(title: str, body: str) -> str:
    payload = f"{_collapse(title)}{SEPARATOR}{_collapse(body)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
