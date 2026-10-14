"""Durable delivery checkpoints, separate from the surveillance database."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path


@dataclass
class NotificationState:
    delivered: str = ""
    observed_at: float = 0.0
    observed: str = ""
    recovery_from: str = ""


@contextmanager
def locked_state(path: Path, channel: str) -> Iterator[NotificationState]:
    """Serialize comparison/send/checkpoint across processes using a local file.

    The operator must create the parent directory on a durable writable mount.
    A missing/corrupt/unwritable store fails closed, before sending anything.
    """
    with closing(sqlite3.connect(path, timeout=1)) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS notification_state ("
            "channel TEXT PRIMARY KEY, delivered TEXT NOT NULL, observed_at REAL NOT NULL, "
            "observed TEXT NOT NULL, recovery_from TEXT NOT NULL)"
        )
        row = connection.execute(
            "SELECT delivered, observed_at, observed, recovery_from "
            "FROM notification_state WHERE channel = ?",
            (channel,),
        ).fetchone()
        state = NotificationState(*row) if row else NotificationState()
        yield state
        connection.execute(
            "INSERT INTO notification_state "
            "(channel, delivered, observed_at, observed, recovery_from) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(channel) DO UPDATE SET "
            "delivered = excluded.delivered, observed_at = excluded.observed_at, "
            "observed = excluded.observed, recovery_from = excluded.recovery_from",
            (channel, state.delivered, state.observed_at, state.observed, state.recovery_from),
        )
