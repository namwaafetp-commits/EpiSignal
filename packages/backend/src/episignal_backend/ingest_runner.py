"""Entry point for `pnpm ingest:who`.

Counts only. Failure detail is kept out of stdout because the connection string
and document bodies would otherwise reach the console.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from episignal_backend.db.session import session_scope
from episignal_backend.ingestion.pipeline import MissingSourceError, run_ingestion
from episignal_backend.ingestion.protocol import SourceConnector
from episignal_backend.ingestion.repository import SqlAlchemySignalRepository
from episignal_backend.ingestion.who_don import WhoDonConnector

CONNECTORS = {"who-don": WhoDonConnector}


@dataclass(frozen=True)
class Arguments:
    connector: str
    since: datetime | None


def _utc_date(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--since must be YYYY-MM-DD") from error


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(prog="ingest", description="Ingest source documents.")
    parser.add_argument("connector", choices=sorted(CONNECTORS))
    parser.add_argument(
        "--since",
        type=_utc_date,
        default=None,
        help="Inclusive UTC start date, YYYY-MM-DD. Defaults to the last 90 days.",
    )
    parsed = parser.parse_args(list(argv))
    return Arguments(connector=parsed.connector, since=parsed.since)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    connector: SourceConnector = CONNECTORS[arguments.connector]()

    try:
        with session_scope() as session:
            result = run_ingestion(
                SqlAlchemySignalRepository(session),
                connector,
                since=arguments.since,
            )
    except MissingSourceError:
        print("Source identity is not seeded. Run pnpm db:seed first.", file=sys.stderr)
        return 1
    except Exception:
        print(
            "Ingestion failed before completing. Check the source and the database.",
            file=sys.stderr,
        )
        return 1

    print(f"inserted={result.inserted} skipped={result.skipped} failed={result.failed}")
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
