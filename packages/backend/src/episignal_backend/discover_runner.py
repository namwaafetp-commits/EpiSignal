"""Entry point for `pnpm discover:gdelt`.

Counts only. Failure detail is kept out of stdout because the connection string
and page bodies would otherwise reach the console.

One run is one polling tick. Scheduling lives outside this repository, so the
interval is configuration this command reads rather than a loop it owns.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.ingestion.discovery import (
    DiscoveryResult,
    RetryResult,
    run_discovery,
    run_retry,
)
from episignal_backend.ingestion.gdelt.api import GdeltDocClient
from episignal_backend.ingestion.gdelt.article import ArticleFetcher
from episignal_backend.ingestion.gdelt.connector import GdeltConnector
from episignal_backend.ingestion.repository import SqlAlchemyDiscoveryRepository


@dataclass(frozen=True)
class Arguments:
    window_minutes: int | None
    max_articles: int | None


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="discover", description="Discover articles through GDELT."
    )
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=None,
        help="Search window in minutes. Defaults to EPISIGNAL_GDELT_QUERY_WINDOW_MINUTES.",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=None,
        help="Pages to retrieve this run. Defaults to EPISIGNAL_GDELT_MAX_ARTICLES_PER_RUN.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(window_minutes=parsed.window_minutes, max_articles=parsed.max_articles)


def _run(arguments: Arguments) -> tuple[RetryResult, DiscoveryResult]:
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
        # Retry first: a stub is a page already known to be wanted, so it has a
        # better claim on the run budget than an article not yet seen.
        retried = run_retry(
            repository,
            connector,
            max_attempts=settings.gdelt_max_retrieval_attempts,
            batch_size=settings.gdelt_retry_batch_size,
        )
        discovered = run_discovery(
            repository,
            connector,
            window_minutes=arguments.window_minutes or settings.gdelt_query_window_minutes,
            max_articles=arguments.max_articles or settings.gdelt_max_articles_per_run,
        )
        return retried, discovered


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        retried, result = _run(arguments)
    except Exception:
        print(
            "Discovery failed before completing. Check GDELT and the database.",
            file=sys.stderr,
        )
        return 1

    if result.rules_run == 0:
        print("No active query rules. Run pnpm db:seed first.", file=sys.stderr)
        return 1

    print(
        f"retried={retried.attempted} promoted={retried.promoted} "
        f"still_failing={retried.still_failing} redundant={retried.redundant}"
    )
    print(
        f"rules={result.rules_run} rules_failed={result.rules_failed} "
        f"discovered={result.discovered} duplicate={result.duplicate} "
        f"deferred={result.deferred} stored={result.stored} "
        f"needs_review={result.needs_review} failed={result.failed}"
    )
    return 1 if result.rules_failed == result.rules_run and result.rules_run else 0


if __name__ == "__main__":
    raise SystemExit(main())
