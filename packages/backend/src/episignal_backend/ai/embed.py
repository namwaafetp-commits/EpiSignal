"""Batch local embeddings for relevant, triaged signals."""

import logging
from dataclasses import dataclass

from episignal_backend.ai.embeddings import EmbeddingProvider, embedding_text, normalize
from episignal_backend.ai.protocol import AiRepository

DEFAULT_BATCH_SIZE = 16

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingResult:
    examined: int = 0
    embedded: int = 0
    failed: int = 0


def run_embedding(
    repository: AiRepository,
    provider: EmbeddingProvider,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> EmbeddingResult:
    pending = repository.awaiting_embeddings(limit=batch_size)
    if not pending:
        return EmbeddingResult()

    texts = tuple(embedding_text(signal.title, signal.raw_text) for signal in pending)
    try:
        vectors = provider.embed(texts)
        embeddings = {
            signal.id: normalize(vector) for signal, vector in zip(pending, vectors, strict=True)
        }
        repository.record_embeddings(embeddings)
        repository.commit()
    except Exception as error:
        repository.rollback()
        logger.error("Could not embed signal batch (%s)", type(error).__name__)
        return EmbeddingResult(examined=len(pending), failed=len(pending))

    return EmbeddingResult(examined=len(pending), embedded=len(pending))
