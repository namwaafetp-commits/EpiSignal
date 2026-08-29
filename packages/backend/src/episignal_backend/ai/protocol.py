"""The two boundaries the AI passes depend on.

`classify.py` and `extract.py` import these and nothing else, so every decision
here is testable with in-memory fakes: no database, no network, no credentials.

The repository owns transactions. Nothing above it knows what a session is,
which is why `commit` and `rollback` sit on this Protocol rather than being
reached for through a handle the passes were given.
"""

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from episignal_backend.ai.documents import (
    AiRequestRecord,
    ChatRequest,
    ChatResponse,
    ClassifiableSignal,
    DiseaseCandidate,
    ExtractableSignal,
    ModelSpec,
    StoredExtraction,
    Verdict,
)
from episignal_backend.db.types import ReviewReason


@runtime_checkable
class ChatModel(Protocol):
    """One request to one model.

    Deliberately one method and no notion of tier: a tier is a model id and a
    price, chosen by the ladder, so one adapter serves the whole ladder.
    """

    def complete(self, request: ChatRequest) -> ChatResponse: ...


@runtime_checkable
class AiRepository(Protocol):
    def models(self) -> Sequence[ModelSpec]: ...

    def awaiting_classification(self, *, limit: int) -> Sequence[ClassifiableSignal]: ...

    def awaiting_extraction(self, *, limit: int) -> Sequence[ExtractableSignal]: ...

    def awaiting_backfill(self, *, limit: int) -> Sequence[ExtractableSignal]: ...

    def resolve_disease(self, name: str) -> UUID | None: ...

    def disease_candidates(self) -> tuple[DiseaseCandidate, ...]: ...

    def resolve_disease_slug(self, slug: str) -> UUID | None: ...

    def record_request(self, record: AiRequestRecord) -> None: ...

    def record_classification(self, signal_id: UUID, verdict: Verdict) -> None: ...

    def record_extraction(self, signal_id: UUID, stored: StoredExtraction) -> None: ...

    def open_review(
        self,
        signal_id: UUID,
        *,
        reason: ReviewReason,
        candidate_scores: Mapping[UUID, float] | None = None,
    ) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class ModelUnavailable(Exception):
    """The provider could not be asked.

    Expected rather than exceptional: free endpoints rate-limit hard and go away
    without notice. Distinct from a rejected answer, because nothing was learned
    about the signal, so the signal must stay exactly as it was.
    """


class NoModelsConfigured(Exception):
    """The roster holds no active row, so there is no ladder to climb."""
