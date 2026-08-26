"""Database readiness reporting.

Only component states leave this module. Exception text, connection strings,
hostnames and PostGIS build details are never propagated to callers because the
result is served over an unauthenticated readiness endpoint.
"""

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from sqlalchemy import Executable, text

ComponentState = Literal["up", "down", "unknown"]

SELECT_ONE = text("SELECT 1")
SELECT_POSTGIS_VERSION = text("SELECT postgis_full_version()")


@dataclass(frozen=True)
class DatabaseHealth:
    database: ComponentState
    postgis: ComponentState

    @property
    def is_ready(self) -> bool:
        return self.database == "up" and self.postgis == "up"


class SupportsScalar(Protocol):
    def scalar(self, statement: Executable, /) -> Any: ...


def check_database(connection: SupportsScalar) -> DatabaseHealth:
    try:
        connection.scalar(SELECT_ONE)
    except Exception:
        return DatabaseHealth(database="down", postgis="unknown")

    try:
        version = connection.scalar(SELECT_POSTGIS_VERSION)
    except Exception:
        return DatabaseHealth(database="up", postgis="down")

    return DatabaseHealth(database="up", postgis="up" if version else "down")
