from collections.abc import Sequence

from episignal_backend.ai.embeddings import (
    EMBEDDING_SNIPPET_CHARACTERS,
    EmbeddingProvider,
    cosine,
    embedding_text,
    normalize,
)


class FakeEmbeddingProvider:
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return tuple([1.0] * 1024 for _ in texts)


def test_a_fake_provider_satisfies_the_protocol() -> None:
    assert isinstance(FakeEmbeddingProvider(), EmbeddingProvider)


def test_embedding_text_joins_the_title_and_the_snippet() -> None:
    assert embedding_text("Dengue in Chiang Mai", "Officials reported...") == (
        "Dengue in Chiang Mai\nOfficials reported..."
    )


def test_the_snippet_is_bounded() -> None:
    text = embedding_text("Title", "x" * 5000)

    assert len(text) <= EMBEDDING_SNIPPET_CHARACTERS + len("Title") + 1


def test_vectors_are_normalized_for_cosine() -> None:
    vector = normalize([3.0, 4.0] + [0.0] * 1022)

    assert abs(sum(value * value for value in vector) - 1.0) < 1e-6


def test_a_zero_vector_normalizes_to_itself_rather_than_dividing_by_zero() -> None:
    assert normalize([0.0] * 1024) == [0.0] * 1024


def test_cosine_similarity_of_normalized_vectors_is_the_inner_product() -> None:
    left = normalize([1.0, 1.0] + [0.0] * 1022)

    assert abs(cosine(left, left) - 1.0) < 1e-6
