from datetime import UTC, datetime

from episignal_backend.schedule.documents import (
    ChainOutcome,
    DiscoveryWindow,
    StageName,
    StageOutcome,
)


def test_stage_names_are_their_lowercase_values() -> None:
    assert StageName.INGEST_WHO == "ingest_who"
    assert StageName.MATCH == "match"


def test_a_window_reports_its_span_in_whole_minutes() -> None:
    window = DiscoveryWindow(
        start=datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
        end=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )

    assert window.minutes == 1440


def test_a_window_shorter_than_a_minute_still_asks_for_one() -> None:
    moment = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)

    assert DiscoveryWindow(start=moment, end=moment).minutes == 1


def test_a_chain_with_no_failures_is_ok() -> None:
    outcome = ChainOutcome(
        outcomes=(
            StageOutcome(stage=StageName.DEDUPE, ok=True, counts={"examined": 3}),
        )
    )

    assert outcome.ok is True
    assert outcome.failed_stages == ()


def test_a_chain_names_every_stage_that_failed() -> None:
    outcome = ChainOutcome(
        outcomes=(
            StageOutcome(stage=StageName.EXTRACT, ok=False, error="TimeoutError"),
            StageOutcome(stage=StageName.GEOCODE, ok=True, counts={"located": 2}),
            StageOutcome(stage=StageName.MATCH, ok=False, error="OperationalError"),
        )
    )

    assert outcome.ok is False
    assert outcome.failed_stages == (StageName.EXTRACT, StageName.MATCH)
