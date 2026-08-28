"""Entry point for `pnpm match:events`.

Counts only. The connection string and article text never reach stdout or stderr.
A failure message says what stage failed and nothing about what was in it.

Re-running is safe: the fresh pass selects only signals at `geocoded`. `--stale`
re-runs signals already at `matched`.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.events.assemble import AssemblySummary, run_event_assembly
from episignal_backend.events.repository import SqlAlchemyEventRepository


@dataclass(frozen=True)
class Arguments:
    limit: int | None
    stale: bool


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="match_events",
        description="Cluster geocoded signals and match them to events.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Signals to examine. Defaults to EPISIGNAL_EVENT_MATCH_BATCH_SIZE.",
    )
    parser.add_argument(
        "--stale",
        action="store_true",
        help="Re-run signals already marked matched.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(limit=parsed.limit, stale=parsed.stale)


def _run(arguments: Arguments) -> AssemblySummary:
    settings = get_settings()
    limit = arguments.limit or settings.event_match_batch_size
    stale = arguments.stale or settings.event_match_stale
    with session_scope() as session:
        return run_event_assembly(
            SqlAlchemyEventRepository(session),
            limit=limit,
            stale=stale,
            cluster_window_days=settings.event_cluster_window_days,
            cluster_distance_km=settings.event_cluster_distance_km,
            match_threshold=settings.event_match_threshold,
            match_recency_days=settings.event_match_recency_days,
            match_distance_km=settings.event_match_distance_km,
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        summary = _run(arguments)
    except Exception as error:
        print(
            f"Event matching failed before completing ({type(error).__name__}). "
            "Check the database and migration state.",
            file=sys.stderr,
        )
        return 1

    print(
        f"seen={summary.signals_seen} clusters={summary.clusters_built} "
        f"created={summary.events_created} attached={summary.signals_attached} "
        f"refused={summary.signals_refused} unclusterable={summary.unclusterable}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
