"""Injectable readiness check.

Routes depend on this callable rather than on the database module so unit tests
can override it and never reach the hosted project.
"""

from episignal_backend.db.session import connection_scope
from episignal_backend.health import DatabaseHealth, check_database


def get_database_health() -> DatabaseHealth:
    try:
        with connection_scope() as connection:
            return check_database(connection)
    except Exception:
        return DatabaseHealth(database="down", postgis="unknown")
