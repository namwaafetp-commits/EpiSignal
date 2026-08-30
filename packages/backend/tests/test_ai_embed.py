from collections.abc import Mapping, Sequence
from uuid import UUID, uuid4

from episignal_backend.ai.documents import ExtractableSignal
from episignal_backend.ai.embed import run_embedding


def signal(title: str) -> ExtractableSignal:
    return ExtractableSignal(id=uuid4(), title=title, raw_text=f"Opening for {title}")


FIRST = signal("Dengue in Chiang Mai")
SECOND = signal("Cholera in Bangkok")
THIRD = signal("Measles in Hanoi")


class EmbedRepository:
    def __init__(self, pending: tuple[ExtractableSignal, ...]) -> None:
        self.pending = pending
        self.embeddings: dict[UUID, list[float]] = {}
        self.commits = 0
        self.rollbacks = 0

    def awaiting_embeddings(self, *, limit: int) -> Sequence[ExtractableSignal]:
        return self.pending[:limit]

    def record_embeddings(self, embeddings: Mapping[UUID, Sequence[float]]) -> None:
        self.embeddings.update(
            {signal_id: list(vector) for signal_id, vector in embeddings.items()}
        )

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.calls += 1
        return tuple([3.0, 4.0] + [0.0] * 1022 for _ in texts)


class FailingProvider:
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        raise RuntimeError("model unavailable")


def test_signals_are_embedded_in_one_batch() -> None:
    repository = EmbedRepository(pending=(FIRST, SECOND, THIRD))
    provider = CountingProvider()

    result = run_embedding(repository, provider, batch_size=16)  # type: ignore[arg-type]

    assert result.embedded == 3
    assert provider.calls == 1


def test_a_stored_vector_is_normalized() -> None:
    repository = EmbedRepository(pending=(FIRST,))

    run_embedding(repository, CountingProvider(), batch_size=16)  # type: ignore[arg-type]

    stored = repository.embeddings[FIRST.id]
    assert abs(sum(value * value for value in stored) - 1.0) < 1e-6


def test_an_already_embedded_signal_is_not_selected() -> None:
    repository = EmbedRepository(pending=())

    assert (  # type: ignore[arg-type]
        run_embedding(repository, CountingProvider(), batch_size=16).embedded == 0
    )


def test_a_provider_failure_leaves_the_batch_unembedded_and_countable() -> None:
    repository = EmbedRepository(pending=(FIRST,))

    result = run_embedding(repository, FailingProvider(), batch_size=16)  # type: ignore[arg-type]

    assert result.failed == 1
    assert repository.embeddings == {}
