"""Entry point for `pnpm extract:backfill`.

Re-extracts signals whose stored extraction predates the current schema. Counts
only on stdout, no secrets or article bodies in logs or errors, and safe to
re-run: signals that have already been upgraded to the current schema are not
selected again.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.ai.extract import ExtractionResult, run_backfill
from episignal_backend.ai.ladder import Guards
from episignal_backend.ai.openrouter import OpenRouterChatModel
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope


@dataclass(frozen=True)
class Arguments:
    limit: int | None


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="backfill",
        description="Re-extract signals whose stored extraction predates the current schema.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Signals to examine. Defaults to EPISIGNAL_AI_SIGNAL_BATCH_LIMIT.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(limit=parsed.limit)


def _run(arguments: Arguments) -> ExtractionResult:
    settings = get_settings()
    if settings.openrouter_api_key is None:
        raise RuntimeError("EPISIGNAL_OPENROUTER_API_KEY is not set")

    model = OpenRouterChatModel(
        settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url,
        timeout_seconds=settings.ai_request_timeout_seconds,
        max_attempts=settings.ai_max_attempts_per_tier,
    )
    guards = Guards(
        max_requests=settings.ai_max_requests_per_run,
        max_cost_usd=settings.ai_max_cost_usd_per_run,
    )
    limit = arguments.limit or settings.ai_signal_batch_limit

    with session_scope() as session:
        return run_backfill(
            SqlAlchemyAiRepository(session),
            model,
            guards=guards,
            limit=limit,
            max_tier=settings.ai_max_tier,
            max_input_characters=settings.ai_max_input_characters,
            min_confidence=settings.ai_min_confidence,
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        result = _run(arguments)
    except Exception as error:
        print(
            f"Backfill failed before completing ({type(error).__name__}). "
            "Check the database and EPISIGNAL_OPENROUTER_API_KEY.",
            file=sys.stderr,
        )
        return 1

    print(
        f"examined={result.examined} extracted={result.extracted} "
        f"review={result.reviewed} unavailable={result.unavailable} "
        f"requests={result.requests} stopped_early={result.stopped_early}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
