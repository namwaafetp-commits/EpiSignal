"""Readiness probe for `pnpm db:check`.

Reports which stage failed - configuration, connection or PostGIS - without
printing the connection string or any driver detail.
"""

import sys

from episignal_backend.db.session import connection_scope
from episignal_backend.health import check_database

from episignal_api.factory import load_runtime_settings


def main() -> int:
    load_runtime_settings()

    try:
        with connection_scope() as connection:
            health = check_database(connection)
    except Exception:
        print("connection: cannot reach the configured database", file=sys.stderr)
        return 1

    if health.database != "up":
        print("connection: the database did not answer a trivial query", file=sys.stderr)
        return 1
    if health.postgis != "up":
        print("postgis: the PostGIS extension is missing or unreadable", file=sys.stderr)
        return 1

    print("database=up postgis=up")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
