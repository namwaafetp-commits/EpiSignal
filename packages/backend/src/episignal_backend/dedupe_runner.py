"""Entry point for `pnpm dedupe:signals`.

Counts only. The connection string and stored bodies never reach stdout, the
same posture as `discover_runner.py`.

Re-running is safe: only signals still awaiting a decision are selected, so a
second run in the same minute does nothing.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.ingestion.dedupe import DedupeResult, DedupeThresholds, run_dedupe
from episignal_backend.ingestion.repository import SqlAlchemyDedupeRepository


@dataclass(frozen=True)
class Arguments:
    batch_size: int | None
    window_hours: int | None


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="dedupe", description="Resolve syndicated copies to one primary signal."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Signals to examine this run. Defaults to EPISIGNAL_STAGE0_BATCH_SIZE.",
    )
    parser.add_argument(
        "--window-hours",
        type=int,
        default=None,
        help="Comparison window. Defaults to EPISIGNAL_STAGE0_CANDIDATE_WINDOW_HOURS.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(batch_size=parsed.batch_size, window_hours=parsed.window_hours)


def _run(arguments: Arguments) -> DedupeResult:
    settings = get_settings()
    with session_scope() as session:
        return run_dedupe(
            SqlAlchemyDedupeRepository(session),
            thresholds=DedupeThresholds(
                title=settings.stage0_title_similarity,
                body=settings.stage0_body_similarity,
                shingle_size=settings.stage0_shingle_size,
            ),
            window_hours=arguments.window_hours or settings.stage0_candidate_window_hours,
            batch_size=arguments.batch_size or settings.stage0_batch_size,
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        result = _run(arguments)
    except Exception:
        print("Deduplication failed before completing. Check the database.", file=sys.stderr)
        return 1

    print(
        f"examined={result.examined} primaries={result.primaries} "
        f"duplicates={result.duplicates} failed={result.failed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
