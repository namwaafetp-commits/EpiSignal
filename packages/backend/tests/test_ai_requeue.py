from typing import Any
from uuid import UUID, uuid4

from episignal_backend.ai.requeue import QUARANTINED_SIGNAL_IDS, requeue_extraction_backlog
from episignal_backend.db.types import ProcessingStatus
from episignal_backend.ingestion.fingerprint import content_hash
from sqlalchemy import Update

QUARANTINE_ID = next(iter(QUARANTINED_SIGNAL_IDS))


class FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalars(self) -> "FakeResult":
        return self

    def all(self) -> list[Any]:
        return list(self._value or [])

    def scalar_one_or_none(self) -> Any:
        return self._value


class FakeSession:
    def __init__(self, results: list[Any] | None = None) -> None:
        self._results = results or []
        self.executed: list[Any] = []
        self.commits = 0

    def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return self._results.pop(0) if self._results else FakeResult(None)

    def commit(self) -> None:
        self.commits += 1


class FakeSignal:
    def __init__(
        self,
        *,
        id: UUID | None = None,
        title: str = "Outbreak title",
        raw_text: str | None = "Outbreak raw text body",
        content_hash_str: str | None = None,
        processing_status: ProcessingStatus = ProcessingStatus.NEEDS_REVIEW,
        public_health_relevant: bool | None = True,
        ai_extraction: dict[str, Any] | None = None,
    ) -> None:
        self.id = id or uuid4()
        self.title = title
        self.raw_text = raw_text
        self.content_hash = (
            content_hash_str
            if content_hash_str is not None
            else (content_hash(title, raw_text) if raw_text else "nohash")
        )
        self.processing_status = processing_status
        self.public_health_relevant = public_health_relevant
        self.ai_extraction = ai_extraction


def test_requeue_extraction_backlog_handles_all_cases() -> None:
    valid_sig = FakeSignal(title="Valid Measles", raw_text="Measles outbreak text")
    quarantine_sig = FakeSignal(id=QUARANTINE_ID, title="Quarantine Measles", raw_text="Body")
    corrupt_sig = FakeSignal(title="Corrupt", raw_text="Body", content_hash_str="invalid_hash")
    discovery_stub = FakeSignal(title="Discovery Stub", raw_text=None, public_health_relevant=None)
    event_fail_sig = FakeSignal(
        title="Event Fail",
        raw_text="Body",
        ai_extraction={"brief": []},
    )

    # Initial query for signals in needs_review returns the 5 signals
    # For valid_sig: query for has_extraction_request returns request ID (uuid4())
    # For event_fail_sig: won't check extraction request because ai_extraction is not None
    signals_result = FakeResult(
        [
            valid_sig,
            quarantine_sig,
            corrupt_sig,
            discovery_stub,
            event_fail_sig,
        ]
    )
    req_result = FakeResult(uuid4())

    session = FakeSession([signals_result, req_result])

    result = requeue_extraction_backlog(session)

    assert result.scanned == 5
    assert result.requeued == 1
    assert result.quarantined_skipped == 1
    assert result.invalid_hash_skipped == 2  # corrupt_sig + discovery_stub
    assert result.non_extraction_skipped == 1  # event_fail_sig
    assert result.requeued_ids == (valid_sig.id,)
    assert session.commits == 1

    # Check update statement executed for valid_sig
    updates = [stmt for stmt in session.executed if isinstance(stmt, Update)]
    assert len(updates) == 1
    params = updates[0].compile().params
    assert ProcessingStatus.CLASSIFIED in params.values()
