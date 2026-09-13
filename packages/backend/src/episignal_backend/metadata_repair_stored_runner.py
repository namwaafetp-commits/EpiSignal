"""Bounded metadata repair from stored extraction evidence only.

This runner requires an explicit event public ID list, defaults to a read-only
dry run, and never discovers events, retrieves articles, or calls an AI model.
"""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from episignal_backend.db.session import enforce_read_only_transaction, session_scope
from episignal_backend.db.types import EventType
from episignal_backend.events.repository import read_stored_extraction
from episignal_backend.metadata import (
    LocalMetadataResolver,
    MetadataEvidence,
    MetadataRepairEvent,
    metadata_evidence_for_signal,
    repair_event_metadata,
)
from episignal_backend.metadata_repository import local_metadata_resolver
from episignal_backend.models import Event, EventSignal, Signal


@dataclass(frozen=True)
class Arguments:
    public_ids: tuple[str, ...]
    apply: bool


@dataclass(frozen=True)
class StoredRepairProposal:
    public_id: str
    old_country: str | None
    old_admin1: str | None
    proposed_country: str | None
    proposed_admin1: str | None
    proposed_disease: object | None
    proposed_event_type: EventType | None


@dataclass(frozen=True)
class StoredRepairResult:
    requested: tuple[str, ...]
    examined: int
    missing: tuple[str, ...]
    proposals: tuple[StoredRepairProposal, ...]
    applied: int = 0


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="metadata:repair-stored",
        description="Preview or apply metadata repairs for explicit event public IDs.",
    )
    parser.add_argument(
        "--public-id",
        dest="public_ids",
        action="append",
        required=True,
        help="Event public ID to examine; repeat for each approved event.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview changes without writing.")
    mode.add_argument("--apply", action="store_true", help="Write proposed metadata in place.")
    clean_argv = [argument for argument in argv if argument != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(public_ids=tuple(dict.fromkeys(parsed.public_ids)), apply=parsed.apply)


def stored_repair_proposal(
    event: Any,
    evidence: Sequence[MetadataEvidence],
    resolver: LocalMetadataResolver,
) -> StoredRepairProposal | None:
    """Build one proposal without reading anything beyond supplied evidence."""
    patch = repair_event_metadata(
        MetadataRepairEvent(
            event_id=event.id,
            country_code=event.country_code,
            admin1=event.admin1,
            disease_id=event.disease_id,
            event_type=event.event_type,
            signals=tuple(evidence),
        ),
        resolver,
    )
    if not patch.changed:
        return None
    return StoredRepairProposal(
        public_id=event.public_id,
        old_country=event.country_code,
        old_admin1=event.admin1,
        proposed_country=patch.country_code,
        proposed_admin1=patch.admin1,
        proposed_disease=patch.disease_id,
        proposed_event_type=patch.event_type,
    )


def run_stored_repair(
    session: Session,
    resolver: LocalMetadataResolver,
    *,
    public_ids: Sequence[str],
    apply: bool = False,
) -> StoredRepairResult:
    requested = tuple(dict.fromkeys(public_ids))
    events = (
        session.execute(
            select(Event).where(Event.public_id.in_(requested)).order_by(Event.public_id)
        )
        .scalars()
        .all()
    )
    found = {event.public_id for event in events}
    proposals: list[StoredRepairProposal] = []
    applied = 0

    for event in events:
        signals = (
            session.execute(
                select(Signal)
                .join(EventSignal, EventSignal.signal_id == Signal.id)
                .where(EventSignal.event_id == event.id)
                .order_by(EventSignal.is_primary.desc(), Signal.first_seen_at, Signal.id)
            )
            .scalars()
            .all()
        )
        evidence = tuple(
            metadata_evidence_for_signal(signal, read_stored_extraction(signal.ai_extraction))
            for signal in signals
        )
        proposal = stored_repair_proposal(event, evidence, resolver)
        if proposal is None:
            continue
        proposals.append(proposal)
        if apply:
            values = {
                key: value
                for key, value in {
                    "country_code": proposal.proposed_country,
                    "admin1": proposal.proposed_admin1,
                    "disease_id": proposal.proposed_disease,
                    "event_type": proposal.proposed_event_type,
                }.items()
                if value is not None
            }
            if values:
                session.execute(update(Event).where(Event.id == event.id).values(**values))
                applied += 1

    if apply:
        session.commit()
    return StoredRepairResult(
        requested=requested,
        examined=len(events),
        missing=tuple(public_id for public_id in requested if public_id not in found),
        proposals=tuple(proposals),
        applied=applied,
    )


def _run(arguments: Arguments) -> StoredRepairResult:
    with session_scope() as session:
        if not arguments.apply:
            enforce_read_only_transaction(session)
        return run_stored_repair(
            session,
            local_metadata_resolver(session),
            public_ids=arguments.public_ids,
            apply=arguments.apply,
        )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        result = _run(arguments)
    except Exception as error:
        print(
            f"Stored metadata repair failed before completing ({type(error).__name__}).",
            file=sys.stderr,
        )
        return 1
    print(
        f"mode={'apply' if arguments.apply else 'dry-run'} "
        f"requested={len(result.requested)} examined={result.examined} "
        f"missing={len(result.missing)} proposals={len(result.proposals)} applied={result.applied}"
    )
    for proposal in result.proposals:
        print(
            f"public_id={proposal.public_id} old_country={proposal.old_country} "
            f"proposed_country={proposal.proposed_country} "
            f"proposed_admin1={proposal.proposed_admin1} "
            f"proposed_disease={proposal.proposed_disease} "
            f"proposed_event_type={proposal.proposed_event_type}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
