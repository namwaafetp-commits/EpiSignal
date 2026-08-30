"""How far back a discovery pass looks.

Discovery's window is anchored to the moment of the run, and nothing else in the
system records how far back it has already looked. On a daily cadence run from a
laptop that sleeps, that would make every hour the machine was off an hour no
run ever asks for again. So the window starts where the last successful run
stopped.
"""

from datetime import datetime, timedelta

from episignal_backend.schedule.documents import DiscoveryWindow


def catch_up_window(
    *,
    now: datetime,
    last_window_end: datetime | None,
    default_minutes: int,
    max_minutes: int,
) -> DiscoveryWindow:
    earliest = now - timedelta(minutes=max_minutes)

    start = now - timedelta(minutes=default_minutes) if last_window_end is None else last_window_end

    # The clamp loses news. It loses it loudly: the run records the window it
    # actually asked for, so a truncated catch-up is a row rather than a hole.
    start = max(start, earliest)
    # A clock that moved backwards must not produce an inverted window.
    start = min(start, now)

    return DiscoveryWindow(start=start, end=now)
