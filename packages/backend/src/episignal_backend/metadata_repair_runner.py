"""Repair missing event metadata in place using reviewed local references."""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from episignal_backend.db.session import session_scope
from episignal_backend.events.repository import read_stored_extraction
from episignal_backend.metadata import (
    MetadataRepairEvent,
    metadata_evidence_for_signal,
    repair_event_metadata,
)
from episignal_backend.metadata_repository import local_metadata_resolver
from episignal_backend.models import Event, EventSignal, Signal


@dataclass(frozen=True)
class Arguments:
    apply: bool
    limit: int | None


@dataclass(frozen=True)
class RepairResult:
    examined: int = 0
    country_resolved: int = 0
    admin1_resolved: int = 0
    disease_resolved: int = 0
    still_unresolved: int = 0


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="metadata-repair",
        description="Repair missing event disease and country metadata from local references.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Report changes without writing them.")
    mode.add_argument("--apply", action="store_true", help="Write resolved metadata in place.")
    parser.add_argument("--limit", type=int, default=None)
    clean_argv = [arg for arg in argv if arg != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(apply=parsed.apply, limit=parsed.limit)


def run_repair(session: Session, *, apply: bool, limit: int | None = None) -> RepairResult:
    resolver = local_metadata_resolver(session)
    statement = (
        select(Event)
        .where(or_(Event.country_code.is_(None), Event.disease_id.is_(None)))
        .order_by(Event.created_at, Event.id)
    )
    if limit is not None:
        statement = statement.limit(limit)
    events = session.execute(statement).scalars().all()

    country_resolved = 0
    admin1_resolved = 0
    disease_resolved = 0
    still_unresolved = 0

    for event in events:
        signal_rows = session.execute(
            select(Signal, EventSignal.is_primary)
            .join(EventSignal, EventSignal.signal_id == Signal.id)
            .where(EventSignal.event_id == event.id)
            .order_by(EventSignal.is_primary.desc(), Signal.first_seen_at, Signal.id)
        ).all()
        evidence = tuple(
            metadata_evidence_for_signal(signal, read_stored_extraction(signal.ai_extraction))
            for signal, _ in signal_rows
        )
        repair_event = MetadataRepairEvent(
            event_id=event.id,
            country_code=event.country_code,
            admin1=event.admin1,
            disease_id=event.disease_id,
            signals=evidence,
        )
        patch = repair_event_metadata(repair_event, resolver)

        country_resolved += int(patch.country_code is not None)
        admin1_resolved += int(patch.admin1 is not None)
        disease_resolved += int(patch.disease_id is not None)

        final_country = event.country_code or patch.country_code
        final_disease = event.disease_id or patch.disease_id
        still_unresolved += int(final_country is None or final_disease is None)

        if apply and patch.changed:
            values = {
                key: value
                for key, value in {
                    "country_code": patch.country_code,
                    "admin1": patch.admin1,
                    "disease_id": patch.disease_id,
                }.items()
                if value is not None
            }
            if values:
                session.execute(update(Event).where(Event.id == event.id).values(**values))

    if apply:
        session.commit()
    return RepairResult(
        examined=len(events),
        country_resolved=country_resolved,
        admin1_resolved=admin1_resolved,
        disease_resolved=disease_resolved,
        still_unresolved=still_unresolved,
    )


def _run(arguments: Arguments) -> RepairResult:
    with session_scope() as session:
        return run_repair(session, apply=arguments.apply, limit=arguments.limit)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        result = _run(arguments)
    except Exception as error:
        print(
            f"Metadata repair failed before completing ({type(error).__name__}). "
            "Check the database and that the local disease and gazetteer data are seeded.",
            file=sys.stderr,
        )
        return 1

    print(
        f"examined={result.examined} country_resolved={result.country_resolved} "
        f"admin1_resolved={result.admin1_resolved} disease_resolved={result.disease_resolved} "
        f"still_unresolved={result.still_unresolved}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
