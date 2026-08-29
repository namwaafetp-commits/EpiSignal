"""Entry point for `pnpm spend:report`.

Prints the trailing spend from the cost ledger: one total line, then one line
per model, purpose, and outcome. The money is the point, so the figures print;
everything else about a request stays in the database.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from episignal_backend.ai.spend import DEFAULT_WINDOW_DAYS, trailing_spend
from episignal_backend.db.session import session_scope


@dataclass(frozen=True)
class Arguments:
    window_days: int


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="spend",
        description="Report trailing AI spend from the cost ledger.",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help="Trailing window. Defaults to 30.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(window_days=parsed.window_days)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        with session_scope() as session:
            summary = trailing_spend(session, window_days=arguments.window_days)
    except Exception as error:
        print(
            f"Spend report failed ({type(error).__name__}). "
            "Check the database and migration state.",
            file=sys.stderr,
        )
        return 1

    print(
        f"window_days={summary.window_days} requests={summary.requests} "
        f"signals={summary.signals} cost_usd={summary.cost_usd}"
    )
    for row in summary.breakdown:
        print(
            f"{row.model_id} {row.purpose} {row.outcome} "
            f"requests={row.requests} signals={row.signals} cost_usd={row.cost_usd}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
