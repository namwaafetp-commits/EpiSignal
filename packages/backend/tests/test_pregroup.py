from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from episignal_backend.db.types import CredibilityTier
from episignal_backend.ingestion.pregroup import PreGroupSignal, group_signals

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def signal(
    *,
    hours: float = 0.0,
    rule_group: str | None = "known_disease",
    country_code: str | None = "CD",
    official: bool = False,
    credibility: CredibilityTier = CredibilityTier.UNKNOWN,
    signal_id=None,
) -> PreGroupSignal:
    return PreGroupSignal(
        signal_id=signal_id or uuid4(),
        rule_group=rule_group,
        country_code=country_code,
        source_is_official=official,
        credibility_tier=credibility,
        first_seen_at=NOW + timedelta(hours=hours),
    )


def test_signals_sharing_key_and_window_form_one_group() -> None:
    groups = group_signals([signal(hours=0), signal(hours=12), signal(hours=30)])

    assert len(groups) == 1
    assert len(groups[0].deferred) == 2


def test_different_countries_never_share_a_group() -> None:
    groups = group_signals([signal(country_code="CD"), signal(country_code="UG")])

    assert len(groups) == 2
    assert {group.country_code for group in groups} == {"CD", "UG"}
    assert all(group.deferred == () for group in groups)


def test_different_rule_groups_never_share_a_group() -> None:
    groups = group_signals([signal(rule_group="known_disease"), signal(rule_group="syndromic")])

    assert len(groups) == 2


def test_a_gap_beyond_the_window_opens_a_new_chain() -> None:
    groups = group_signals([signal(hours=0), signal(hours=24 * 5)], window_days=1)

    assert len(groups) == 2
    assert groups[0].rule_group == groups[1].rule_group


def test_a_signal_without_rule_or_country_forms_its_own_group() -> None:
    lone = signal(rule_group=None, country_code=None)
    groups = group_signals([lone, signal()])

    assert len(groups) == 2
    singles = [group for group in groups if group.key == (None, None)]
    assert len(singles) == 1
    assert singles[0].representative.signal_id == lone.signal_id
    assert singles[0].deferred == ()


def test_the_official_source_represents_over_an_earlier_unknown() -> None:
    official = signal(hours=10, official=True)
    unknown = signal(hours=0, official=False)
    groups = group_signals([official, unknown])

    assert groups[0].representative.signal_id == official.signal_id


def test_higher_credibility_represents_at_equal_officialness() -> None:
    high = signal(hours=10, credibility=CredibilityTier.HIGH)
    medium = signal(hours=0, credibility=CredibilityTier.MEDIUM)
    groups = group_signals([high, medium])

    assert groups[0].representative.signal_id == high.signal_id


def test_the_earliest_sighting_wins_at_equal_standing() -> None:
    earlier = signal(hours=0)
    later = signal(hours=3)
    groups = group_signals([later, earlier])

    assert groups[0].representative.signal_id == earlier.signal_id


def test_the_uuid_breaks_a_perfect_tie() -> None:
    first = signal(hours=0, signal_id=uuid4())
    second = signal(hours=0, signal_id=uuid4())
    groups = group_signals([second, first])

    expected = min(first, second, key=lambda s: str(s.signal_id))
    assert groups[0].representative.signal_id == expected.signal_id


def test_the_window_is_capped_by_the_stage() -> None:
    with pytest.raises(ValueError):
        group_signals([signal()], window_days=3)
