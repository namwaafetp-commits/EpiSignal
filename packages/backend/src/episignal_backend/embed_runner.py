"""Entry point for ``pnpm embed:signals``."""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.ai.embed import EmbeddingResult, run_embedding
from episignal_backend.ai.embeddings import LocalBgeM3Provider
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope


@dataclass(frozen=True)
class Arguments:
    batch_size: int | None


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="embed",
        description="Embed one bounded batch of relevant triaged signals.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Signals to embed. Defaults to EPISIGNAL_EMBEDDING_BATCH_SIZE.",
    )
    clean_argv = [argument for argument in argv if argument != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(batch_size=parsed.batch_size)


def _run(arguments: Arguments) -> EmbeddingResult:
    settings = get_settings()
    batch_size = arguments.batch_size or settings.embedding_batch_size
    provider = LocalBgeM3Provider(
        model_name=settings.embedding_model,
        batch_size=batch_size,
    )
    with session_scope() as session:
        return run_embedding(
            SqlAlchemyAiRepository(session),
            provider,
            batch_size=batch_size,
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        result = _run(arguments)
    except Exception:
        print(
            "Embedding failed before completing. Check the model cache and database.",
            file=sys.stderr,
        )
        return 1

    print(f"examined={result.examined} embedded={result.embedded} failed={result.failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
