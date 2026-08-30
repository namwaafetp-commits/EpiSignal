"""Entry point for `pnpm pregroup:signals`.

Groups normalized signals into pre-groups and defers every member but each
group's representative. Refuses to run — politely, successfully — while the
stage is disabled, because the flag is the design's measurement gate, not an
operational convenience.

Counts only, like every runner: nothing about a signal's text reaches stdout.
Re-running is safe: signals already carrying a membership are never selected
as candidates.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.ingestion.pregroup import group_signals
from episignal_backend.ingestion.pregroup_store import SqlAlchemyPreGroupStore


@dataclass(frozen=True)
class Arguments:
    limit: int | None


@dataclass(frozen=True)
class PreGroupResult:
    examined: int
    groups: int
    deferred: int
    resolved: int
    expired: int


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="pregroup",
        description="Group normalized signals so one representative per story is extracted.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Signals to examine. Defaults to EPISIGNAL_PREGROUP_BATCH_SIZE.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(limit=parsed.limit)


def _run(arguments: Arguments) -> PreGroupResult:
    settings = get_settings()
    limit = arguments.limit or settings.pregroup_batch_size
    now = datetime.now(UTC)

    with session_scope() as session:
        store = SqlAlchemyPreGroupStore(session)
        resolved, expired = store.resolve_and_expire(
            expiry_hours=settings.pregroup_expiry_hours, now=now
        )
        candidates = store.candidates(limit=limit)
        groups = group_signals(candidates, window_days=settings.pregroup_window_days)
        written = store.write_groups(groups, window_days=settings.pregroup_window_days, now=now)
        session.commit()

    deferred = sum(len(group.deferred) for group in groups)
    return PreGroupResult(
        examined=len(candidates),
        groups=written,
        deferred=deferred,
        resolved=resolved,
        expired=expired,
    )


def main(argv: Sequence[str] | None = None) -> int:
    settings = get_settings()
    if not settings.pregroup_enabled:
        # Disabled stops new deferrals; it never strands old ones. Closing
        # open groups is two UPDATEs, so it runs even now — otherwise a flag
        # flipped mid-flight would leave deferred signals unselectable
        # forever, and "nothing is permanently unseen" is the stage's
        # binding promise.
        try:
            with session_scope() as session:
                resolved, expired = SqlAlchemyPreGroupStore(session).resolve_and_expire(
                    expiry_hours=settings.pregroup_expiry_hours,
                    now=datetime.now(UTC),
                )
                session.commit()
        except Exception as error:
            print(
                f"Pre-group close-out failed ({type(error).__name__}). "
                "Check the database and migration state.",
                file=sys.stderr,
            )
            return 1
        print(f"pregroup=disabled resolved={resolved} expired={expired}")
        return 0

    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        result = _run(arguments)
    except Exception as error:
        print(
            f"Pre-grouping failed before completing ({type(error).__name__}). "
            "Check the database and migration state.",
            file=sys.stderr,
        )
        return 1

    print(
        f"examined={result.examined} groups={result.groups} deferred={result.deferred} "
        f"resolved={result.resolved} expired={result.expired}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
