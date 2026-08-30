"""Sentence embeddings, behind one seam.

Clustering must never import a model library. Everything above this module sees
``EmbeddingProvider``, so a local model can be swapped for a hosted endpoint
without touching a single matching rule.

Vectors are L2-normalized here rather than at query time, so cosine similarity
is an inner product and the pgvector index measures what the code claims.
"""

import math
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

EMBEDDING_DIMENSIONS = 1024
EMBEDDING_SNIPPET_CHARACTERS = 1200


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


def embedding_text(title: str, snippet: str) -> str:
    """Join the headline to a bounded opening paragraph for embedding."""
    return f"{title}\n{snippet[:EMBEDDING_SNIPPET_CHARACTERS]}"


def normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        # A zero vector has no direction. Returning it unchanged keeps the
        # caller honest rather than inventing one.
        return list(vector)
    return [value / norm for value in vector]


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


class LocalBgeM3Provider:
    """BAAI/bge-m3, loaded once and held for the life of the worker.

    Construction is expensive because it loads roughly two gigabytes of
    weights. The scheduled stage builds one provider per run and the manual
    runner builds one per process.
    """

    def __init__(self, model_name: str = "BAAI/bge-m3", batch_size: int = 16) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self._batch_size = batch_size

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if not texts:
            return ()
        vectors = self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=False,
            show_progress_bar=False,
        )
        return tuple(normalize(vector.tolist()) for vector in vectors)
