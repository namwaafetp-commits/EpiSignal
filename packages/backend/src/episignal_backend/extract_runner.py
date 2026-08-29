"""Entry point for `pnpm extract:signals`.

Counts only. The API key, the prompts, and the article bodies never reach
stdout or stderr, the same posture as `discover_runner.py` and
`dedupe_runner.py`. A failure message says what stage failed and nothing about
what was in it.

Re-running is safe: each pass selects only signals still awaiting its decision,
so a second run in the same minute does nothing.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from episignal_backend.ai.classify import ClassificationResult, run_classification
from episignal_backend.ai.extract import ExtractionResult, run_extraction
from episignal_backend.ai.ladder import Guards
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.ai.routing import NoProviderKey, RoutedChatModel, build_adapters
from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope

Stage = Literal["classify", "extract", "both"]


@dataclass(frozen=True)
class Arguments:
    limit: int | None
    batch_size: int | None
    stage: Stage


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="extract",
        description="Classify normalized signals and extract epidemiological facts.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Signals to examine per pass. Defaults to EPISIGNAL_AI_SIGNAL_BATCH_LIMIT.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Signals per classification request. Defaults to EPISIGNAL_AI_BATCH_SIZE.",
    )
    parser.add_argument(
        "--stage",
        choices=("classify", "extract", "both"),
        default="both",
        help="Which pass to run.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(limit=parsed.limit, batch_size=parsed.batch_size, stage=parsed.stage)


def _run(arguments: Arguments) -> tuple[ClassificationResult, ExtractionResult]:
    settings = get_settings()
    try:
        adapters = build_adapters(
            openrouter_api_key=(
                settings.openrouter_api_key.get_secret_value()
                if settings.openrouter_api_key
                else None
            ),
            gemini_api_key=(
                settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
            ),
            openrouter_base_url=settings.openrouter_base_url,
            gemini_base_url=settings.gemini_base_url,
            timeout_seconds=settings.ai_request_timeout_seconds,
            max_attempts=settings.ai_max_attempts_per_tier,
        )
    except NoProviderKey as error:
        raise RuntimeError(str(error)) from error

    guards = Guards(
        max_requests=settings.ai_max_requests_per_run,
        max_cost_usd=settings.ai_max_cost_usd_per_run,
    )
    limit = arguments.limit or settings.ai_signal_batch_limit
    batch_size = arguments.batch_size or settings.ai_batch_size

    classified = ClassificationResult()
    extracted = ExtractionResult()

    with session_scope() as session:
        repository = SqlAlchemyAiRepository(session)
        model = RoutedChatModel.from_specs(list(repository.models()), adapters)
        if arguments.stage in {"classify", "both"}:
            classified = run_classification(
                repository,
                model,
                guards=guards,
                batch_size=batch_size,
                limit=limit,
                max_tier=settings.ai_max_tier,
                max_input_characters=settings.ai_max_input_characters,
            )
        if arguments.stage in {"extract", "both"}:
            extracted = run_extraction(
                repository,
                model,
                guards=guards,
                limit=limit,
                max_tier=settings.ai_max_tier,
                max_input_characters=settings.ai_max_input_characters,
                min_confidence=settings.ai_min_confidence,
            )

    return classified, extracted


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        classified, extracted = _run(arguments)
    except Exception as error:
        # The message is fixed text plus the exception's type, never its
        # payload: an exception raised near a prompt can carry the article, and
        # one raised near the client can carry the key.
        print(
            f"Extraction failed before completing ({type(error).__name__}). "
            "Check the database and the provider keys "
            "(EPISIGNAL_OPENROUTER_API_KEY, EPISIGNAL_GEMINI_API_KEY).",
            file=sys.stderr,
        )
        return 1

    print(
        f"classified={classified.examined} relevant={classified.relevant} "
        f"irrelevant={classified.irrelevant} extracted={extracted.extracted} "
        f"review={classified.reviewed + extracted.reviewed} "
        f"unavailable={classified.unavailable + extracted.unavailable} "
        f"requests={classified.requests + extracted.requests} "
        f"stopped_early={classified.stopped_early or extracted.stopped_early}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
