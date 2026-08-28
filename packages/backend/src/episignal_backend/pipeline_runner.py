"""Entry point for `pnpm pipeline:run`.

Counts and stage names only. The connection string, the article text, and the
API key never reach stdout or stderr; a stage failure is reported as the
exception's type and nothing about what was in it.

Re-running is safe: every stage selects its own backlog by processing_status. A
second run started while one is in progress takes no lock, prints that a run is
in progress, and exits 0 — a skipped overlap is the correct outcome.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.db.types import PipelineChain, PipelineRunStatus, PipelineTrigger
from episignal_backend.schedule.chains import chain_for
from episignal_backend.schedule.documents import ChainOutcome, StageName
from episignal_backend.schedule.repository import SqlAlchemyPipelineRunRepository
from episignal_backend.schedule.run import run_chain
from episignal_backend.schedule.stages import build_stage_runners
from episignal_backend.schedule.window import catch_up_window


@dataclass(frozen=True)
class Arguments:
    only: StageName | None
    trigger: str


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="pipeline_run",
        description="Run the daily pipeline chain once.",
    )
    parser.add_argument(
        "--only",
        type=StageName,
        choices=list(StageName),
        default=None,
        help="Run one stage instead of the whole chain.",
    )
    parser.add_argument(
        "--trigger",
        choices=["scheduled", "manual"],
        default="manual",
        help="Who started this run. Task Scheduler passes scheduled.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(only=parsed.only, trigger=parsed.trigger)


def _print(outcome: ChainOutcome, backlog: dict[str, int]) -> None:
    for stage in outcome.outcomes:
        if stage.ok:
            counts = " ".join(f"{key}={value}" for key, value in stage.counts.items())
            print(f"{stage.stage} ok {counts}".rstrip())
        else:
            print(f"{stage.stage} failed ({stage.error})")
    print("backlog " + " ".join(f"{key}={value}" for key, value in sorted(backlog.items())))


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    settings = get_settings()
    chain_name = PipelineChain(settings.pipeline_chain)
    chain = chain_for(settings.pipeline_chain)
    if arguments.only is not None:
        chain = (arguments.only,)

    try:
        with session_scope() as session:
            repository = SqlAlchemyPipelineRunRepository(session)
            if not repository.try_lock():
                print("A pipeline run is already in progress; nothing to do.")
                return 0

            try:
                started_at = datetime.now(UTC)
                window = catch_up_window(
                    now=started_at,
                    last_window_end=repository.last_window_end(chain_name),
                    default_minutes=settings.gdelt_query_window_minutes,
                    max_minutes=settings.pipeline_catch_up_max_minutes,
                )
                run_id = repository.start_run(
                    chain=chain_name,
                    trigger=PipelineTrigger(arguments.trigger),
                    started_at=started_at,
                    window=window if StageName.DISCOVER in chain else None,
                )

                outcome = run_chain(chain, build_stage_runners(window=window))
                backlog = repository.backlog_depth()

                repository.finish_run(
                    run_id,
                    status=(
                        PipelineRunStatus.SUCCEEDED if outcome.ok else PipelineRunStatus.FAILED
                    ),
                    finished_at=datetime.now(UTC),
                    stage_counts={str(item.stage): dict(item.counts) for item in outcome.outcomes},
                    backlog=backlog,
                    failed_stages=list(outcome.failed_stages),
                )
            finally:
                repository.unlock()
    except Exception as error:
        print(
            f"The pipeline run failed before completing ({type(error).__name__}). "
            "Check the database and the migration state.",
            file=sys.stderr,
        )
        return 1

    _print(outcome, backlog)
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
