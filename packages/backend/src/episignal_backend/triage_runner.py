"""Entry point for ``pnpm triage:signals``.

Only aggregate counts reach stdout. Provider errors, prompts, and article text
stay out of the console so a failed manual run cannot leak evidence or keys.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.ai.ladder import Guards
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.ai.routing import NoProviderKey, routed_from_settings
from episignal_backend.ai.triage import TriageResult, run_triage
from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope


@dataclass(frozen=True)
class Arguments:
    limit: int | None


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="triage",
        description="Add early structured metadata to normalized signals.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Signals to examine. Defaults to EPISIGNAL_AI_TRIAGE_BATCH_LIMIT.",
    )
    clean_argv = [argument for argument in argv if argument != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(limit=parsed.limit)


def _run(arguments: Arguments) -> TriageResult:
    settings = get_settings()
    guards = Guards(
        max_requests=settings.ai_max_requests_per_run,
        max_cost_usd=settings.ai_max_cost_usd_per_run,
    )

    with session_scope() as session:
        repository = SqlAlchemyAiRepository(session)
        try:
            model = routed_from_settings(settings, list(repository.models()))
        except NoProviderKey as error:
            raise RuntimeError(str(error)) from error
        return run_triage(
            repository,
            model,
            guards=guards,
            limit=arguments.limit or settings.ai_triage_batch_limit,
            max_tier=settings.ai_max_tier,
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        result = _run(arguments)
    except Exception:
        print(
            "Triage failed before completing. Check the database and provider keys.",
            file=sys.stderr,
        )
        return 1

    print(
        f"examined={result.examined} triaged={result.triaged} repaired={result.repaired} "
        f"filtered={result.filtered} failed={result.failed} "
        f"unavailable={result.unavailable} requests={result.requests} "
        f"stopped_early={result.stopped_early}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
