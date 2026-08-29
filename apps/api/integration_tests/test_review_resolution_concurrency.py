"""PostgreSQL concurrency contention test for manual review resolution.

Guarded by EPISIGNAL_TEST_DATABASE_URL to ensure isolated, safe live execution.
"""

import os
import threading
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from episignal_backend.db.models import Signal, SignalReviewCase
from episignal_backend.db.types import (
    ProcessingStatus,
    ReviewReason,
    ReviewResolution,
    ReviewStatus,
    SourceType,
)
from episignal_backend.review.documents import DismissCommand, ReviewAlreadyResolved
from episignal_backend.review.repository import SqlAlchemyReviewRepository


def _get_test_db_url() -> str | None:
    url = os.getenv("EPISIGNAL_TEST_DATABASE_URL")
    prod_url = os.getenv("EPISIGNAL_DATABASE_URL")
    if not url:
        return None
    if prod_url and url == prod_url:
        raise ValueError("EPISIGNAL_TEST_DATABASE_URL must not equal EPISIGNAL_DATABASE_URL")
    return url


@pytest.mark.skipif(
    not os.getenv("EPISIGNAL_TEST_DATABASE_URL"),
    reason="Requires EPISIGNAL_TEST_DATABASE_URL for live PostgreSQL concurrency test",
)
def test_concurrent_review_resolution_exactly_one_succeeds() -> None:
    test_db_url = _get_test_db_url()
    assert test_db_url is not None

    engine = create_engine(test_db_url, pool_size=5, max_overflow=5)
    SessionLocal = sessionmaker(bind=engine)

    # 1. Seed a test signal and open review case in setup session
    with SessionLocal() as setup_session:
        signal = Signal(
            source_id=uuid4(),
            source_url="https://test.example/concurrent-test",
            source_type=SourceType.LOCAL_MEDIA,
            title="Concurrency Test Signal",
            raw_text="Sample raw text for concurrency verification.",
            processing_status=ProcessingStatus.NEEDS_REVIEW,
        )
        setup_session.add(signal)
        setup_session.flush()

        case = SignalReviewCase(
            signal_id=signal.id,
            reason=ReviewReason.EXTRACTION_FAILED,
            status=ReviewStatus.OPEN,
        )
        setup_session.add(case)
        setup_session.commit()

        case_id = case.id
        signal_id = signal.id

    barrier = threading.Barrier(2)
    results: list[Exception | None] = [None, None]

    def _worker(worker_idx: int) -> None:
        try:
            with SessionLocal() as worker_session:
                barrier.wait(timeout=10)
                repo = SqlAlchemyReviewRepository(worker_session)
                cmd = DismissCommand(
                    case_id=case_id,
                    reviewed_by=f"worker-{worker_idx}",
                    note=f"Concurrent resolution by worker {worker_idx}",
                )
                repo.resolve_review(case_id, cmd)
                worker_session.commit()
                results[worker_idx] = None
        except Exception as exc:
            results[worker_idx] = exc

    t0 = threading.Thread(target=_worker, args=(0,))
    t1 = threading.Thread(target=_worker, args=(1,))

    t0.start()
    t1.start()
    t0.join(timeout=15)
    t1.join(timeout=15)

    # Exactly one succeeded and one raised ReviewAlreadyResolved
    success_count = sum(1 for r in results if r is None)
    conflict_count = sum(1 for r in results if isinstance(r, ReviewAlreadyResolved))

    assert success_count == 1
    assert conflict_count == 1

    # In a verification session, assert the case is resolved once and signal is dismissed
    with SessionLocal() as verify_session:
        final_case = verify_session.execute(
            select(SignalReviewCase).where(SignalReviewCase.id == case_id)
        ).scalar_one()
        final_signal = verify_session.execute(
            select(Signal).where(Signal.id == signal_id)
        ).scalar_one()

        assert final_case.status == ReviewStatus.RESOLVED
        assert final_case.resolution == ReviewResolution.DISMISS
        assert final_case.reviewed_by in ("worker-0", "worker-1")
        assert final_signal.processing_status == ProcessingStatus.DISMISSED
