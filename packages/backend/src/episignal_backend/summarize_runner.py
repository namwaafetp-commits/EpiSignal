"""Entry point for `pnpm summarize:events`.

Counts only, like the other runners. Summarization is keyed off the
``event_summaries`` history and ``events.last_summarized_at``, so a re-run is
idempotent: an event whose counts have not changed since its last summary is
left alone, and an accepted summary is appended as a new version, never an
overwrite.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from episignal_backend.ai.ladder import cost_row
from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.config import get_settings
from episignal_backend.db.session import session_scope
from episignal_backend.db.types import AiPurpose
from episignal_backend.events.repository import SqlAlchemyEventRepository
from episignal_backend.events.summarize import (
    SummaryOutcome,
    configure_summary,
    has_usable_summary_source,
    legacy_summary_fields,
    render_event_flash_brief,
    run_summary,
    should_resummarize,
    summary_payload,
    summary_title,
    unique_summary_candidates,
)


@dataclass(frozen=True)
class Arguments:
    limit: int | None


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="summarize_events",
        description="Regenerate event summaries when a material change warrants it.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Events to examine. Defaults to EPISIGNAL_EVENT_MATCH_BATCH_SIZE.",
    )
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(limit=parsed.limit)


def _run(arguments: Arguments) -> dict[str, int]:
    settings = get_settings()
    limit = arguments.limit or settings.event_match_batch_size
    now = datetime.now(UTC)

    with session_scope() as session:
        repository = SqlAlchemyEventRepository(session)
        specs = list(SqlAlchemyAiRepository(session).models())
        wiring = configure_summary(settings, specs)

        awaiting = repository.events_awaiting_summary(
            limit=limit,
            max_age_hours=settings.resummary_max_age_hours,
        )

        examined = 0
        skipped = 0
        skipped_no_change = 0
        skipped_no_model = 0
        skipped_no_sources = 0
        summarized = 0
        failed = 0
        unavailable = 0

        for event in unique_summary_candidates(awaiting):
            examined += 1
            if not should_resummarize(
                last_summarized_at=event.last_summarized_at,
                latest_observation=event.latest_observation,
                previous_counts=event.previous_counts,
                unsummarized_articles=event.unsummarized_articles,
                now=now,
                max_age_hours=settings.resummary_max_age_hours,
                new_article_count=settings.resummary_new_article_count,
            ):
                skipped += 1
                skipped_no_change += 1
                continue

            sources = event.sources
            if not has_usable_summary_source(sources):
                skipped += 1
                skipped_no_sources += 1
                continue

            if wiring.model is None or wiring.spec is None:
                # No summarizer configured: the event keeps its current
                # narrative. Counted as skipped rather than failed.
                skipped += 1
                skipped_no_model += 1
                continue

            # The contract requires consolidated evidence from every linked
            # source; representative-source caps belong to the old summary.
            result = run_summary(
                wiring.model,
                wiring.spec,
                event=event,
                sources=sources,
            )
            if result.attempt is not None:
                repository.record_ai_request(
                    cost_row(
                        result.attempt,
                        purpose=AiPurpose.EVENT_SUMMARY,
                        signal_id=None,
                        batch_size=1,
                        at=now,
                    )
                )
            if result.outcome is SummaryOutcome.ACCEPTED and result.verdict is not None:
                trajectory, snapshot, key_driver, response, risk = legacy_summary_fields(
                    result.verdict
                )
                repository.store_summary(
                    event_id=event.event_id,
                    headline=summary_title(result.verdict),
                    summary=render_event_flash_brief(result.verdict),
                    trajectory=trajectory,
                    snapshot=snapshot,
                    key_driver=key_driver,
                    response=response,
                    risk=risk,
                    model_id=wiring.spec.model_id,
                    source_signal_ids=[source.signal_id for source in sources],
                    counts=event.latest_observation,
                    now=now,
                    summary_payload=summary_payload(result.verdict),
                )
                summarized += 1
            elif result.outcome is SummaryOutcome.UNAVAILABLE:
                unavailable += 1
            else:
                failed += 1

        repository.commit()

    return {
        "examined": examined,
        "skipped": skipped,
        "skipped_no_change": skipped_no_change,
        "skipped_no_model": skipped_no_model,
        "skipped_no_sources": skipped_no_sources,
        "summarized": summarized,
        "failed": failed,
        "unavailable": unavailable,
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)

    try:
        counts = _run(arguments)
    except Exception as error:
        print(
            f"Event summarization failed before completing ({type(error).__name__}). "
            "Check the database and migration state.",
            file=sys.stderr,
        )
        return 1

    print(
        f"examined={counts['examined']} skipped={counts['skipped']} "
        f"skipped_no_change={counts['skipped_no_change']} "
        f"skipped_no_model={counts['skipped_no_model']} "
        f"skipped_no_sources={counts['skipped_no_sources']} "
        f"summarized={counts['summarized']} failed={counts['failed']} "
        f"unavailable={counts['unavailable']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
