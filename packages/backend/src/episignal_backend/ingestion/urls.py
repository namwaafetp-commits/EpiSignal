"""URL canonicalization.

Two URLs that differ only by tracking parameters, a fragment, host casing or a
trailing slash name the same document. Path case is preserved because document
identifiers such as `2026-DON615` are case-sensitive on the origin server.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMETERS = frozenset(
    {
        "gclid",
        "fbclid",
    }
)


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    parameters = sorted(
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not name.lower().startswith("utm_") and name.lower() not in TRACKING_PARAMETERS
    )
    path = parsed.path if parsed.path == "/" else parsed.path.rstrip("/")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            urlencode(parameters),
            "",
        )
    )
