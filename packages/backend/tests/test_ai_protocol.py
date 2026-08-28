from collections.abc import Sequence
from uuid import UUID, uuid4

from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatRequest,
    ChatResponse,
    ClassifiableSignal,
    ExtractableSignal,
    ModelSpec,
    StoredExtraction,
    TokenUsage,
    Verdict,
)
from episignal_backend.ai.protocol import AiRepository, ChatModel


class StubModel:
    def complete(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(content="{}", usage=TokenUsage(), http_status=200, latency_ms=1)


class StubRepository:
    def models(self) -> Sequence[ModelSpec]:
        return ()

    def awaiting_classification(self, *, limit: int) -> Sequence[ClassifiableSignal]:
        return ()

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]:
        return ()

    def awaiting_backfill(self, *, limit: int) -> Sequence[ExtractableSignal]:
        return ()

    def resolve_disease(self, name: str) -> UUID | None:
        return None

    def record_request(self, record: AiRequestRecord) -> None:
        return None

    def record_classification(self, signal_id: UUID, verdict: Verdict) -> None:
        return None

    def record_extraction(self, signal_id: UUID, stored: StoredExtraction) -> None:
        return None

    def mark_needs_review(self, signal_id: UUID) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def test_a_chat_model_is_recognised_by_its_single_method() -> None:
    assert isinstance(StubModel(), ChatModel)


def test_a_repository_is_recognised_by_the_whole_storage_boundary() -> None:
    assert isinstance(StubRepository(), AiRepository)


def test_an_object_missing_a_storage_method_is_not_a_repository() -> None:
    class Partial:
        def models(self) -> Sequence[ModelSpec]:
            return ()

    assert not isinstance(Partial(), AiRepository)


def test_the_repository_owns_committing_and_rolling_back() -> None:
    repository = StubRepository()

    assert hasattr(repository, "commit")
    assert hasattr(repository, "rollback")
    assert uuid4() is not None
