import json
from pathlib import Path

from episignal_backend.ingestion.similarity import (
    body_similarity,
    normalize_title,
    title_similarity,
)

FIXTURES = Path(__file__).parent / "fixtures"
SHINGLE_SIZE = 5


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def gdelt_titles() -> list[str]:
    payload = json.loads(read("gdelt_artlist.json"))
    return [article["title"] for article in payload["articles"]]


def test_affiliate_furniture_is_dropped_from_a_syndicated_title() -> None:
    first, second, _ = gdelt_titles()

    assert normalize_title(first) == normalize_title(second)


def test_two_syndicated_titles_are_identical_after_normalization() -> None:
    first, second, _ = gdelt_titles()

    assert title_similarity(first, second) == 1.0


def test_a_headline_containing_a_spaced_hyphen_is_not_truncated() -> None:
    _, _, scottish = gdelt_titles()

    tokens = normalize_title(scottish)

    assert "voyage" in tokens
    assert "highlander" in tokens


def test_unrelated_titles_are_not_similar() -> None:
    first, _, scottish = gdelt_titles()

    assert title_similarity(first, scottish) < 0.5


def test_syndicated_bodies_are_similar_despite_different_boilerplate() -> None:
    similarity = body_similarity(
        read("syndicated_body_a.txt"), read("syndicated_body_b.txt"), size=SHINGLE_SIZE
    )

    assert similarity >= 0.80


def test_an_independent_report_on_the_same_event_is_not_similar() -> None:
    similarity = body_similarity(
        read("syndicated_body_a.txt"), read("independent_body.txt"), size=SHINGLE_SIZE
    )

    assert similarity < 0.80


def test_an_empty_body_never_matches() -> None:
    assert body_similarity("", "", size=SHINGLE_SIZE) == 0.0
    assert body_similarity("", read("independent_body.txt"), size=SHINGLE_SIZE) == 0.0


def test_a_body_shorter_than_the_shingle_is_compared_whole() -> None:
    assert body_similarity("Cholera in Juba", "Cholera in Juba", size=SHINGLE_SIZE) == 1.0
    assert body_similarity("Cholera in Juba", "Measles in Lima", size=SHINGLE_SIZE) == 0.0
