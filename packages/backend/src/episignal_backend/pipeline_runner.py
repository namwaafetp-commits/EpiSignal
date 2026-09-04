"""Entry point for `pnpm pipeline:run`.

Counts and stage names only. The connection string, the article text, and the
API key never reach stdout or stderr; a stage failure is reported as the
exception's type and nothing about what was in it.

Re-running is safe: every stage selects its own backlog by processing_status. A
second run started while one is in progress takes no lock, prints that a run is
in progress, and exits 0 — a skipped overlap is the correct outcome.
"""

import argparse
import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.db.types import PipelineChain, PipelineRunStatus, PipelineTrigger
from episignal_backend.monitoring_repository import persist_pipeline_health_best_effort
from episignal_backend.operational_monitoring import build_health_record
from episignal_backend.requeue import requeue_historical_extractions
from episignal_backend.schedule.chains import chain_for
from episignal_backend.schedule.documents import ChainOutcome, PipelineCohort, StageName
from episignal_backend.schedule.repository import SqlAlchemyPipelineRunRepository
from episignal_backend.schedule.run import run_chain
from episignal_backend.schedule.stages import build_stage_runners
from episignal_backend.schedule.window import catch_up_window

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Arguments:
    only: StageName | None
    trigger: str
    requeue_existing: bool = False


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="pipeline_run",
        description="Run the daily pipeline chain once.",
    )
    parser.add_argument(
        "--only",
        type=StageName,
        choices=list(chain_for("daily")),
        default=None,
        help="Run one stage instead of the whole chain.",
    )
    parser.add_argument(
        "--trigger",
        choices=["scheduled", "manual"],
        default="manual",
        help="Who started this run. Task Scheduler passes scheduled.",
    )
    parser.add_argument(
        "--requeue-existing",
        action="store_true",
        help="Requeue eligible historical extractions, then run match and summarize only.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(
        only=parsed.only,
        trigger=parsed.trigger,
        requeue_existing=parsed.requeue_existing,
    )


def _print(outcome: ChainOutcome, backlog: dict[str, int]) -> None:
    for stage in outcome.outcomes:
        if stage.ok:
            counts = " ".join(f"{key}={value}" for key, value in stage.counts.items())
            print(f"{stage.stage} ok {counts}".rstrip())
        else:
            print(f"{stage.stage} failed ({stage.error})")
    print("backlog " + " ".join(f"{key}={value}" for key, value in sorted(backlog.items())))


def _persist_health_best_effort(
    *,
    run_id: UUID,
    started_at: datetime,
    finished_at: datetime | None,
    outcome: ChainOutcome,
    fatal_error_type: str | None = None,
) -> None:
    try:
        persist_pipeline_health_best_effort(
            build_health_record(
                run_id=run_id,
                started_at=started_at,
                finished_at=finished_at,
                outcome=outcome,
                fatal_error_type=fatal_error_type,
            )
        )
    except Exception as error:
        logger.warning("Pipeline health persistence unavailable (%s)", type(error).__name__)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    settings = get_settings()
    chain_name = PipelineChain(settings.pipeline_chain)
    chain = chain_for(settings.pipeline_chain)
    requeued = 0
    if arguments.requeue_existing:
        chain = (StageName.MATCH, StageName.SUMMARIZE)
    if arguments.only is not None:
        chain = (arguments.only,)

    run_id: UUID | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    outcome: ChainOutcome | None = None
    backlog: dict[str, int] = {}
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
                if arguments.requeue_existing:
                    requeue_result = requeue_historical_extractions(session)
                    requeued = requeue_result.requeued
                run_id = repository.start_run(
                    chain=chain_name,
                    trigger=PipelineTrigger(arguments.trigger),
                    started_at=started_at,
                    window=window if StageName.DISCOVER in chain else None,
                )
                # Make the parent durable before stage work so a fatal exception
                # can still leave a linked failed health row behind.
                session.commit()

                outcome = run_chain(
                    chain,
                    build_stage_runners(window=window, cohort=PipelineCohort()),
                )
                backlog = repository.backlog_depth()

                finished_at = datetime.now(UTC)
                repository.finish_run(
                    run_id,
                    status=(
                        PipelineRunStatus.SUCCEEDED if outcome.ok else PipelineRunStatus.FAILED
                    ),
                    finished_at=finished_at,
                    stage_counts={str(item.stage): dict(item.counts) for item in outcome.outcomes},
                    backlog=backlog,
                    failed_stages=[item for item in outcome.outcomes if not item.ok],
                )
            finally:
                repository.unlock()
        if run_id is not None and started_at is not None and outcome is not None:
            _persist_health_best_effort(
                run_id=run_id,
                started_at=started_at,
                finished_at=finished_at,
                outcome=outcome,
            )
    except Exception as error:
        if run_id is not None and started_at is not None:
            _persist_health_best_effort(
                run_id=run_id,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                outcome=outcome or ChainOutcome(outcomes=()),
                fatal_error_type=type(error).__name__,
            )
        print(
            f"The pipeline run failed before completing ({type(error).__name__}). "
            "Check the database and the migration state.",
            file=sys.stderr,
        )
        return 1

    assert outcome is not None
    _print(outcome, backlog)
    if arguments.requeue_existing:
        print(f"requeued_existing={requeued}")
    return 0 if outcome.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
