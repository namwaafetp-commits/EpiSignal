"""Repair approved disease IDs on historical signals without reprocessing them."""

import argparse
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Select, Update, or_, select, update
from sqlalchemy.orm import Session

from episignal_backend.ai.repository import SqlAlchemyAiRepository
from episignal_backend.db.session import enforce_read_only_transaction, session_scope
from episignal_backend.models import Disease, Signal

APPROVED_DISEASES: dict[str, str] = {
    "rabies": "Rabies",
    "west-nile-virus-disease": "West Nile virus disease",
    "avian-influenza": "Avian influenza",
}
APPROVED_CANONICAL_NAMES = frozenset(APPROVED_DISEASES.values())
DiseaseResolver = Callable[[str], UUID | None]


@dataclass(frozen=True)
class Arguments:
    apply: bool


@dataclass(frozen=True)
class RepairCandidate:
    signal_id: UUID
    raw_disease_text: str
    resolved_canonical_name: str
    proposed_disease_id: UUID


@dataclass(frozen=True)
class RepairResult:
    candidates: tuple[RepairCandidate, ...]
    applied: int = 0
    skipped: int = 0

    @property
    def counts_by_canonical(self) -> Counter[str]:
        return Counter(candidate.resolved_canonical_name for candidate in self.candidates)


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="repair_historical_diseases",
        description="Repair only NULL signal disease IDs for three approved diseases.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview repairs without writing.")
    mode.add_argument("--apply", action="store_true", help="Apply qualifying repairs.")
    clean_argv = [argument for argument in argv if argument != "--"]
    parsed = parser.parse_args(clean_argv)
    return Arguments(apply=parsed.apply)


def _nonblank_texts(current: str | None, old: str | None) -> tuple[str, ...]:
    return tuple(value for value in (current, old) if isinstance(value, str) and value.strip())


def build_repair_candidate(
    *,
    signal_id: UUID,
    existing_disease_id: UUID | None,
    current_disease_text: str | None,
    old_disease_text: str | None,
    resolve_disease: DiseaseResolver,
    approved_diseases: Mapping[UUID, str],
) -> RepairCandidate | None:
    """Build one proposal only when every stored disease value agrees exactly."""
    if existing_disease_id is not None:
        return None

    texts = _nonblank_texts(current_disease_text, old_disease_text)
    if not texts:
        return None

    resolved: list[tuple[UUID, str]] = []
    for text in texts:
        disease_id = resolve_disease(text)
        if disease_id is None:
            return None
        canonical_name = approved_diseases.get(disease_id)
        if canonical_name not in APPROVED_CANONICAL_NAMES:
            return None
        resolved.append((disease_id, canonical_name))

    if len({disease_id for disease_id, _ in resolved}) != 1:
        return None

    disease_id, canonical_name = resolved[0]
    raw_text = texts[0]
    return RepairCandidate(
        signal_id=signal_id,
        raw_disease_text=raw_text,
        resolved_canonical_name=canonical_name,
        proposed_disease_id=disease_id,
    )


def historical_signal_statement() -> Select[tuple[UUID, str | None, str | None]]:
    current_disease_text = Signal.ai_extraction["disease_text"].as_string()
    old_disease_text = Signal.ai_extraction["disease"]["name"].as_string()
    return select(
        Signal.id,
        current_disease_text.label("current_disease_text"),
        old_disease_text.label("old_disease_text"),
    ).where(
        Signal.disease_id.is_(None),
        Signal.ai_extraction.is_not(None),
        or_(current_disease_text.is_not(None), old_disease_text.is_not(None)),
    )


def find_repair_candidates(session: Session) -> tuple[RepairCandidate, ...]:
    approved_rows = session.execute(
        select(Disease.id, Disease.canonical_name, Disease.slug).where(
            Disease.slug.in_(tuple(APPROVED_DISEASES))
        )
    ).all()
    approved_diseases = {
        disease_id: APPROVED_DISEASES[slug]
        for disease_id, canonical_name, slug in approved_rows
        if APPROVED_DISEASES.get(slug) == canonical_name
    }
    resolver = SqlAlchemyAiRepository(session)
    candidates: list[RepairCandidate] = []
    for signal_id, current_text, old_text in session.execute(historical_signal_statement()).all():
        candidate = build_repair_candidate(
            signal_id=signal_id,
            existing_disease_id=None,
            current_disease_text=current_text,
            old_disease_text=old_text,
            resolve_disease=resolver.resolve_disease,
            approved_diseases=approved_diseases,
        )
        if candidate is not None:
            candidates.append(candidate)
    return tuple(candidates)


def repair_update_statement(candidate: RepairCandidate) -> Update:
    return (
        update(Signal)
        .where(Signal.id == candidate.signal_id, Signal.disease_id.is_(None))
        .values(disease_id=candidate.proposed_disease_id)
    )


def run_repair(session: Session, *, apply: bool) -> RepairResult:
    candidates = find_repair_candidates(session)
    if not apply:
        return RepairResult(candidates=candidates)

    applied = 0
    skipped = 0
    for candidate in candidates:
        result = session.execute(repair_update_statement(candidate))
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
            f"signal_id={candidate.signal_id} "
            f"raw_disease_text={candidate.raw_disease_text!r} "
            f"resolved_canonical={candidate.resolved_canonical_name!r} "
            f"proposed_disease_id={candidate.proposed_disease_id}"
        )
    counts = result.counts_by_canonical
    for canonical_name in APPROVED_DISEASES.values():
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
            f"Historical disease repair failed ({type(error).__name__}). "
            "Check the database and migration state.",
            file=sys.stderr,
        )
        return 1

    _print_result(result, apply=arguments.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
