"""Entry point for `pnpm retrieve:gdelt`.

Counts only. Failure detail is kept out of stdout because the connection string
and page bodies would otherwise reach the console.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.ingestion.gdelt.api import GdeltDocClient
from episignal_backend.ingestion.gdelt.article import ArticleFetcher
from episignal_backend.ingestion.gdelt.connector import GdeltConnector
from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository
from episignal_backend.ingestion.retrieval import RetrievalResult, run_retrieval


@dataclass(frozen=True)
class Arguments:
    max_attempts: int | None
    batch_size: int | None


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="retrieve", description="Retrieve article bodies after keyword gating."
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=None,
        help="Max attempts per signal. Defaults to EPISIGNAL_GDELT_MAX_RETRIEVAL_ATTEMPTS.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Articles to fetch this run. Defaults to EPISIGNAL_GDELT_RETRY_BATCH_SIZE.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(max_attempts=parsed.max_attempts, batch_size=parsed.batch_size)


def _run(arguments: Arguments) -> RetrievalResult:
    settings = get_settings()
    connector = GdeltConnector(
        search=GdeltDocClient(),
        fetcher=ArticleFetcher(
            delay_seconds=settings.gdelt_article_delay_seconds,
            user_agent=settings.gdelt_user_agent,
            timeout_seconds=settings.gdelt_article_timeout_seconds,
        ),
    )
    with session_scope() as session:
        repository = SqlAlchemyDiscoveryRepository(session)
        result = run_retrieval(
            repository,
            connector,
            max_attempts=arguments.max_attempts or settings.gdelt_max_retrieval_attempts,
            batch_size=arguments.batch_size or settings.gdelt_retry_batch_size,
            window_hours=settings.stage0_candidate_window_hours,
        )
        return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        result = _run(arguments)
    except Exception:
        print(
            "Retrieval failed before completing. Check the publisher connections and the database.",
            file=sys.stderr,
        )
        return 1

    print(
        f"examined={result.examined} filtered={result.filtered} "
        f"retrieved={result.retrieved} duplicates={result.duplicates} redundant={result.redundant} "
        f"still_failing={result.still_failing} failed={result.failed}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
