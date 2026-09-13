"""Repair missing event disease IDs from the approved historical signal scope."""

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, Update, exists, select, update
from sqlalchemy.orm import Session, aliased

from episignal_backend.db.session import enforce_read_only_transaction, session_scope
from episignal_backend.models import Disease, Event, EventSignal, Signal

APPROVED_CANONICAL_NAMES = frozenset(
    {
        "Rabies",
        "West Nile virus disease",
        "Avian influenza",
    }
)

# Exact signal IDs selected and repaired by the approved historical signal
# repair. This immutable scope prevents later signals with matching vocabulary
# from entering this one-time event repair.
APPROVED_HISTORICAL_SIGNAL_IDS = (
    UUID("0481a3ec-fbbb-44d2-9e2b-1c5fb7638ed6"),
    UUID("06d1bc9a-22d1-476c-8acc-9ea796f0ff58"),
    UUID("0909ea04-abaf-45bd-88d4-e936179b0720"),
    UUID("0a7da0dc-2e89-4900-981f-fcb4f6384260"),
    UUID("0f9e1b48-567e-423c-85a8-ae8af521dd06"),
    UUID("16d0fec6-b92a-49e3-a1c6-3d7894c46965"),
    UUID("1c3085ab-8aec-4fbc-a65f-8a9a7d7eaf0f"),
    UUID("2e2fdb41-b082-4da5-be8d-3bc85095d731"),
    UUID("3141377e-f72b-46e7-932f-83090290ea9c"),
    UUID("492d175a-3254-483f-b5bf-6c39000696c0"),
    UUID("7a81110e-e398-433c-bf0a-7be3afab8677"),
    UUID("90eeee8b-8c60-43e0-8ce2-613013a476d7"),
    UUID("91c104d3-98c9-4ef6-bd87-0e26be334cc7"),
    UUID("a6d29500-ebf6-4215-bc9b-0275f4d8bea9"),
    UUID("cdb3ee03-5a9b-41e7-bf34-1e3f2eb48330"),
    UUID("d4c7a10b-6f83-41eb-80f5-7d8bc79bc891"),
    UUID("d597e679-2831-44b0-a68f-ab1486881d56"),
    UUID("d5f59106-e30a-46e3-9d7a-f9c8127ed6ab"),
    UUID("e96eddd8-3f6c-4ce3-8472-155f65dde5d3"),
    UUID("eb3ddf02-4555-4e28-92c4-9dbdce7d666f"),
)


@dataclass(frozen=True)
class Arguments:
    apply: bool


@dataclass(frozen=True)
class EventRepairCandidate:
    event_id: UUID
    signal_id: UUID
    canonical_name: str
    current_event_disease_id: UUID | None
    proposed_disease_id: UUID


@dataclass(frozen=True)
class RepairResult:
    candidates: tuple[EventRepairCandidate, ...]
    applied: int = 0
    skipped: int = 0

    @property
    def counts_by_canonical(self) -> Counter[str]:
        return Counter(candidate.canonical_name for candidate in self.candidates)


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="repair_historical_event_diseases",
        description="Repair only missing event diseases from approved historical signals.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview repairs without writing.")
    mode.add_argument("--apply", action="store_true", help="Apply qualifying repairs.")
    clean_argv = [argument for argument in argv if argument != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(apply=parsed.apply)


def build_event_repair_candidate(
    *,
    event_id: UUID,
    signal_id: UUID,
    current_event_disease_id: UUID | None,
    attached_signal_count: int,
    signal_disease_id: UUID | None,
    canonical_name: str | None,
    approved_signal_ids: Sequence[UUID],
    approved_disease_ids: Sequence[UUID],
) -> EventRepairCandidate | None:
    """Build a proposal only when event and its sole signal pass every guard."""
    if current_event_disease_id is not None:
        return None
    if attached_signal_count != 1:
        return None
    if signal_id not in approved_signal_ids:
        return None
    if (
        signal_disease_id is None
        or signal_disease_id not in approved_disease_ids
        or canonical_name not in APPROVED_CANONICAL_NAMES
    ):
        return None
    return EventRepairCandidate(
        event_id=event_id,
        signal_id=signal_id,
        canonical_name=canonical_name,
        current_event_disease_id=current_event_disease_id,
        proposed_disease_id=signal_disease_id,
    )


def eligible_event_statement(
    *,
    approved_signal_ids: Sequence[UUID] = APPROVED_HISTORICAL_SIGNAL_IDS,
    approved_disease_ids: Sequence[UUID],
) -> Select[tuple[UUID, UUID, UUID | None, str, UUID | None]]:
    """Select NULL-disease events with exactly one approved repaired signal."""
    candidate_event_signal = aliased(EventSignal)
    other_event_signal = aliased(EventSignal)
    return (
        select(
            Event.id,
            candidate_event_signal.signal_id,
            Signal.disease_id,
            Disease.canonical_name,
            Event.disease_id,
        )
        .join(candidate_event_signal, candidate_event_signal.event_id == Event.id)
        .join(Signal, Signal.id == candidate_event_signal.signal_id)
        .join(Disease, Disease.id == Signal.disease_id)
        .where(
            Event.disease_id.is_(None),
            candidate_event_signal.signal_id.in_(tuple(approved_signal_ids)),
            Signal.disease_id.is_not(None),
            Signal.disease_id.in_(tuple(approved_disease_ids)),
            Disease.canonical_name.in_(tuple(APPROVED_CANONICAL_NAMES)),
            ~exists(
                select(1).where(
                    other_event_signal.event_id == Event.id,
                    other_event_signal.signal_id != candidate_event_signal.signal_id,
                )
            ),
        )
        .order_by(Event.id)
    )


def find_repair_candidates(session: Session) -> tuple[EventRepairCandidate, ...]:
    approved_rows = session.execute(
        select(Disease.id, Disease.canonical_name).where(
            Disease.canonical_name.in_(tuple(APPROVED_CANONICAL_NAMES))
        )
    ).all()
    approved_disease_ids = tuple(row[0] for row in approved_rows)
    candidates: list[EventRepairCandidate] = []
    rows = session.execute(
        eligible_event_statement(approved_disease_ids=approved_disease_ids)
    ).all()
    for event_id, signal_id, signal_disease_id, canonical_name, event_disease_id in rows:
        candidate = build_event_repair_candidate(
            event_id=event_id,
            signal_id=signal_id,
            current_event_disease_id=event_disease_id,
            attached_signal_count=1,
            signal_disease_id=signal_disease_id,
            canonical_name=canonical_name,
            approved_signal_ids=APPROVED_HISTORICAL_SIGNAL_IDS,
            approved_disease_ids=approved_disease_ids,
        )
        if candidate is not None:
            candidates.append(candidate)
    return tuple(candidates)


def event_repair_statement(candidate: EventRepairCandidate) -> Update:
    same_signal = (
        select(1)
        .select_from(EventSignal)
        .join(Signal, Signal.id == EventSignal.signal_id)
        .where(
            EventSignal.event_id == Event.id,
            EventSignal.signal_id == candidate.signal_id,
            Signal.disease_id == candidate.proposed_disease_id,
        )
    )
    extra_signal = (
        select(1)
        .select_from(EventSignal)
        .where(
            EventSignal.event_id == Event.id,
            EventSignal.signal_id != candidate.signal_id,
        )
    )
    return (
        update(Event)
        .where(
            Event.id == candidate.event_id,
            Event.disease_id.is_(None),
            exists(same_signal),
            ~exists(extra_signal),
        )
        .values(disease_id=candidate.proposed_disease_id)
    )


def run_repair(session: Session, *, apply: bool) -> RepairResult:
    candidates = find_repair_candidates(session)
    if not apply:
        return RepairResult(candidates=candidates)

    applied = 0
    skipped = 0
    for candidate in candidates:
        result = session.execute(event_repair_statement(candidate))
        if getattr(result, "rowcount", 0) == 1:
            applied += 1
        else:
            skipped += 1
    return RepairResult(candidates=candidates, applied=applied, skipped=skipped)


def _print_result(result: RepairResult, *, apply: bool) -> None:
    mode = "apply" if apply else "dry-run"
    print(f"mode={mode}")
    for candidate in result.candidates:
        print(
            f"event_id={candidate.event_id} "
            f"signal_id={candidate.signal_id} "
            f"canonical_disease={candidate.canonical_name!r} "
            f"current_event_disease_id={candidate.current_event_disease_id} "
            f"proposed_disease_id={candidate.proposed_disease_id}"
        )
    counts = result.counts_by_canonical
    for canonical_name in ("Rabies", "West Nile virus disease", "Avian influenza"):
        print(f"{canonical_name}: {counts[canonical_name]}")
    print(f"total_candidates={len(result.candidates)}")
    if apply:
        print(f"applied={result.applied} skipped_concurrent={result.skipped}")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        with session_scope() as session:
            if not arguments.apply:
                enforce_read_only_transaction(session)
            result = run_repair(session, apply=arguments.apply)
    except Exception as error:
        print(
            f"Historical event disease repair failed ({type(error).__name__}). "
            "Check the database and migration state.",
            file=sys.stderr,
        )
        return 1

    _print_result(result, apply=arguments.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
