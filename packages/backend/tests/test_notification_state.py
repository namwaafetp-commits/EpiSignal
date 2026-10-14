import sqlite3
from pathlib import Path

import pytest


def test_notification_state_survives_reopening_and_isolates_channels(tmp_path: Path):
    from episignal_backend.notification_state import locked_state

    path = tmp_path / "notifications.sqlite3"
    with locked_state(path, "alerts:destination") as state:
        assert state.delivered == ""
        state.delivered = "warning:retrieval"
        state.observed_at = 100.0
    with locked_state(path, "alerts:destination") as state:
        assert state.delivered == "warning:retrieval"
        assert state.observed_at == 100.0
    with locked_state(path, "daily:destination") as state:
        assert state.delivered == ""


def test_notification_state_rolls_back_and_releases_lock_on_error(tmp_path):
    from episignal_backend.notification_state import locked_state

    path = tmp_path / "notifications.sqlite3"
    with pytest.raises(RuntimeError), locked_state(path, "alerts") as state:
        state.delivered = "not committed"
        raise RuntimeError("simulated crash")
    with locked_state(path, "alerts") as state:
        assert state.delivered == ""


def test_notification_state_rejects_overlapping_writer(tmp_path):
    from episignal_backend.notification_state import locked_state

    path = tmp_path / "notifications.sqlite3"
    with (
        locked_state(path, "alerts"),
        pytest.raises(sqlite3.OperationalError, match="locked"),
        locked_state(path, "alerts"),
    ):
        pytest.fail("concurrent send must not enter critical section")
