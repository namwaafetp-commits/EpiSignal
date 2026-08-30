from datetime import UTC, datetime
from uuid import uuid4

import pytest
from episignal_backend.db.types import FilterRuleGroup
from episignal_backend.ingestion.documents import ComparableSignal, FilterRule, Rejection
from pydantic import ValidationError

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


def test_filter_rule_carries_its_group_and_pattern() -> None:
    rule = FilterRule(
        id=uuid4(),
        rule_group=FilterRuleGroup.TITLE_EXCLUSION,
        pattern=r"\bviral video\b",
        label="Viral content",
    )

    assert rule.rule_group is FilterRuleGroup.TITLE_EXCLUSION
    assert rule.pattern == r"\bviral video\b"


def test_filter_rule_rejects_a_blank_pattern() -> None:
    with pytest.raises(ValidationError):
        FilterRule(rule_group=FilterRuleGroup.DOMAIN_BLOCKLIST, pattern="", label="Empty")


def test_rejection_requires_an_aware_rejected_at() -> None:
    with pytest.raises(ValidationError):
        Rejection(
            url="https://example.com/a",
            canonical_url="https://example.com/a",
            title="Outbreak of violence in the capital",
            domain="example.com",
            rejected_at=datetime(2026, 8, 27, 9, 0),
        )


def test_rejection_allows_a_missing_sighting_time() -> None:
    rejection = Rejection(
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        title="Outbreak of violence in the capital",
        domain="example.com",
        rejected_at=NOW,
    )

    assert rejection.gdelt_seen_at is None
    assert rejection.filter_rule_id is None


def test_comparable_signal_requires_body_text() -> None:
    with pytest.raises(ValidationError):
        ComparableSignal(
            id=uuid4(),
            canonical_url="https://example.com/a",
            title="Measles cases rise",
            raw_text="   ",
            content_hash="a" * 64,
            first_seen_at=NOW,
        )


def test_comparable_signal_defaults_to_no_primary() -> None:
    signal = ComparableSignal(
        id=uuid4(),
        canonical_url="https://example.com/a",
        title="Measles cases rise",
        raw_text="Eighteen cases were confirmed.",
        content_hash="a" * 64,
        first_seen_at=NOW,
    )

    assert signal.published_at is None
    assert signal.duplicate_of_signal_id is None
