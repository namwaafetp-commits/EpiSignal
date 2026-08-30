from datetime import UTC, datetime, timedelta

from episignal_backend.schedule.window import catch_up_window

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def test_the_first_run_ever_falls_back_to_the_configured_window() -> None:
    window = catch_up_window(now=NOW, last_window_end=None, default_minutes=1500, max_minutes=10080)

    assert window.end == NOW
    assert window.start == NOW - timedelta(minutes=1500)


def test_a_later_run_starts_where_the_last_one_stopped() -> None:
    previous_end = NOW - timedelta(hours=26)

    window = catch_up_window(
        now=NOW, last_window_end=previous_end, default_minutes=1500, max_minutes=10080
    )

    assert window.start == previous_end
    assert window.end == NOW
    assert window.minutes == 26 * 60


def test_a_long_gap_is_clamped_rather_than_asked_for_in_full() -> None:
    window = catch_up_window(
        now=NOW,
        last_window_end=NOW - timedelta(days=90),
        default_minutes=1500,
        max_minutes=10080,
    )

    assert window.start == NOW - timedelta(minutes=10080)
    assert window.minutes == 10080


def test_a_last_window_end_in_the_future_does_not_invert_the_window() -> None:
    # A clock change, or a row written by a machine whose clock was ahead.
    window = catch_up_window(
        now=NOW,
        last_window_end=NOW + timedelta(hours=3),
        default_minutes=1500,
        max_minutes=10080,
    )

    assert window.start == NOW
    assert window.end == NOW
    assert window.minutes == 1
