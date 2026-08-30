import pytest
from episignal_backend.ingestion.urls import canonicalize_url

ITEM = "https://www.who.int/emergencies/disease-outbreak-news/item/2026-DON615"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (ITEM, ITEM),
        (f"{ITEM}#summary", ITEM),
        (f"{ITEM}/", ITEM),
        (f"{ITEM}?utm_source=newsletter&utm_campaign=x", ITEM),
        (f"{ITEM}?UTM_creative_format=card&utm_id=42", ITEM),
        (f"{ITEM}?gclid=abc&fbclid=def", ITEM),
        ("HTTPS://WWW.WHO.INT/emergencies", "https://www.who.int/emergencies"),
        (f"{ITEM}?b=2&a=1", f"{ITEM}?a=1&b=2"),
        ("https://www.who.int/", "https://www.who.int/"),
        (f"{ITEM}?note=100%25done", f"{ITEM}?note=100%25done"),
        (f"{ITEM}?a=1&a=2", f"{ITEM}?a=1&a=2"),
    ],
)
def test_canonicalize_url_removes_noise_without_changing_identity(raw: str, expected: str) -> None:
    assert canonicalize_url(raw) == expected


def test_canonicalize_url_preserves_path_case() -> None:
    assert canonicalize_url(ITEM).endswith("2026-DON615")


def test_canonicalize_url_keeps_meaningful_query_parameters() -> None:
    assert canonicalize_url(f"{ITEM}?page=2") == f"{ITEM}?page=2"


def test_canonicalize_url_is_idempotent() -> None:
    once = canonicalize_url(f"{ITEM}/?utm_source=x#top")
    assert canonicalize_url(once) == once
