"""Entry point for `pnpm geocode:signals`.

Counts only. The connection string and the article text never reach stdout or
stderr, the same posture as `extract_runner.py`. A failure message says what
stage failed and nothing about what was in it.

Re-running is safe: the fresh pass selects only signals still at `extracted`, so
a second run in the same minute does nothing. `--stale` re-runs signals whose
rows were written against a superseded gazetteer.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.geocode.external import NominatimClient
from episignal_backend.geocode.locate import GeocodingResult, run_geocoding
from episignal_backend.geocode.repository import (
    SqlAlchemyGazetteerRepository,
    SqlAlchemyGeocodeCacheRepository,
    SqlAlchemyGeocodeRepository,
)


@dataclass(frozen=True)
class Arguments:
    limit: int | None
    stale: bool


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="geocode",
        description="Resolve the places named by extracted signals.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Signals to examine. Defaults to EPISIGNAL_GEOCODE_BATCH_SIZE.",
    )
    parser.add_argument(
        "--stale",
        action="store_true",
        help="Re-run signals whose locations came from a superseded gazetteer.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(limit=parsed.limit, stale=parsed.stale)


def _run(arguments: Arguments) -> GeocodingResult:
    settings = get_settings()
    limit = min(
        arguments.limit or settings.geocode_batch_size,
        settings.geocode_max_signals_per_run,
    )
    with session_scope() as session:
        # The cache is a local table, so it is always in play; the live client
        # is built only when the operator has enabled Nominatim, and otherwise
        # the pass never reaches the network. Both ride the run's session, so
        # cache writes commit — or roll back — with everything else.
        return run_geocoding(
            SqlAlchemyGeocodeRepository(session),
            SqlAlchemyGazetteerRepository(session),
            limit=limit,
            source=settings.gazetteer_source,
            stale=arguments.stale,
            cache=SqlAlchemyGeocodeCacheRepository(session),
            nominatim=(
                NominatimClient(
                    base_url=settings.nominatim_url,
                    user_agent=settings.nominatim_user_agent,
                    timeout=settings.nominatim_timeout_seconds,
                )
                if settings.nominatim_enabled
                else None
            ),
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        result = _run(arguments)
    except Exception as error:
        # The message is fixed text plus the exception's type, never its
        # payload: an exception raised near the session can carry the
        # connection string.
        print(
            f"Geocoding failed before completing ({type(error).__name__}). "
            "Check the database, the migration state, and that the gazetteer is seeded.",
            file=sys.stderr,
        )
        return 1

    print(
        f"examined={result.examined} located={result.located} "
        f"unresolved={result.unresolved} locations={result.locations}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
