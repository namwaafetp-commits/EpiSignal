from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from episignal_backend.db.types import ProcessingStatus
from episignal_backend.ingestion.documents import (
    DiscoveredArticle,
    DiscoveredSignal,
    Publisher,
    QueryRule,
    TimeWindow,
)

SEEN = datetime(2026, 8, 26, 7, 45, tzinfo=UTC)
ICT = timezone(timedelta(hours=7))


def article(**overrides: object) -> DiscoveredArticle:
    values: dict[str, object] = {
        "url": "https://example.vn/a",
        "canonical_url": "https://example.vn/a",
        "title": "Eighteen students hospitalised",
        "domain": "example.vn",
        "gdelt_seen_at": SEEN,
        "language": "vi",
        "country_code": "VN",
    }
    return DiscoveredArticle(**(values | overrides))  # type: ignore[arg-type]


def test_article_rejects_a_naive_seen_time() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        article(gdelt_seen_at=datetime(2026, 8, 26, 7, 45))


def test_article_lowercases_its_domain() -> None:
    assert article(domain="Example.VN").domain == "example.vn"


def test_article_rejects_a_blank_domain() -> None:
    with pytest.raises(ValidationError):
        article(domain="   ")


def test_signal_may_carry_no_body_and_no_publication_time() -> None:
    signal = DiscoveredSignal(
        url="https://example.vn/a",
        canonical_url="https://example.vn/a",
        title="Eighteen students hospitalised",
        raw_text=None,
        published_at=None,
        published_at_offset_minutes=None,
        retrieved_at=SEEN,
        first_seen_at=SEEN,
        gdelt_seen_at=SEEN,
        language="vi",
        content_hash="a" * 64,
        publisher=Publisher(domain="example.vn", name="Example", language="vi", country_code="VN"),
        processing_status=ProcessingStatus.NEEDS_REVIEW,
    )
    assert signal.raw_text is None
    assert signal.published_at is None


def test_signal_preserves_the_publisher_offset() -> None:
    signal = DiscoveredSignal(
        url="https://example.vn/a",
        canonical_url="https://example.vn/a",
        title="Eighteen students hospitalised",
        raw_text="Eighteen students were admitted.",
        published_at=datetime(2026, 8, 26, 7, 42, tzinfo=ICT),
        published_at_offset_minutes=420,
        retrieved_at=SEEN,
        first_seen_at=SEEN,
        gdelt_seen_at=SEEN,
        language="vi",
        content_hash="b" * 64,
        publisher=Publisher(domain="example.vn", name="Example", language="vi", country_code="VN"),
    )
    assert signal.published_at_offset_minutes == 420


def test_query_rule_and_window_are_frozen() -> None:
    rule = QueryRule(id=None, rule_group="syndromic", query='"unknown fever"', label="Unknown fever")
    window = TimeWindow(start=SEEN, end=SEEN)
    with pytest.raises(ValidationError):
        rule.query = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        window.start = SEEN  # type: ignore[misc]


def test_window_rejects_an_end_before_its_start() -> None:
    with pytest.raises(ValidationError, match="end"):
        TimeWindow(start=SEEN, end=SEEN - timedelta(minutes=1))


def test_stub_retrieval_rejects_a_negative_attempt_count() -> None:
    from uuid import uuid4

    from episignal_backend.ingestion.documents import StubRetrieval

    with pytest.raises(ValidationError):
        StubRetrieval(signal_id=uuid4(), article=article(), first_seen_at=SEEN, attempts=-1)
