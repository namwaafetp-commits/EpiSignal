"""Entry point for `pnpm db:seed`.

One transaction, counts only. Failure detail is deliberately not printed because
the connection string and rejected rows would otherwise reach the console.
"""

import sys

from episignal_backend.db.session import session_scope
from episignal_backend.seeds import seed_database


def main() -> int:
    try:
        with session_scope() as session:
            result = seed_database(session)
    except Exception:
        print("Seeding failed. Check EPISIGNAL_DATABASE_URL and migration state.", file=sys.stderr)
        return 1
    print(
        f"diseases={result.diseases} sources={result.sources} "
        f"query_rules={result.query_rules}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
