"""Recover missing event metadata through the normal extraction seam."""

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from episignal_backend.ai.documents import ExtractableSignal, StoredExtraction
from episignal_backend.ai.extract import (
    DEFAULT_MAX_INPUT_CHARACTERS,
    DEFAULT_MIN_CONFIDENCE,
    ExtractionSignalResult,
    build_extraction_ladder,
    extract_signal,
)
from episignal_backend.ai.ladder import Guards, RunBudget, cost_row
from episignal_backend.ai.protocol import AiRepository, ChatModel
from episignal_backend.db.session import enforce_read_only_transaction, session_scope
from episignal_backend.db.types import AiPurpose, EventType
from episignal_backend.events.repository import read_stored_extraction
from episignal_backend.metadata import (
    LocalMetadataResolver,
    MetadataEvidence,
    MetadataRepairEvent,
    ResolvedMetadata,
    metadata_evidence_for_signal,
    metadata_fields_from_extraction,
    repair_event_metadata,
    resolve_repair_evidence,
)
from episignal_backend.metadata_repository import local_metadata_resolver
from episignal_backend.models import Event, EventSignal, Signal, Source


@dataclass(frozen=True)
class Arguments:
    apply: bool
    enforce_read_only: bool
    limit: int | None
    max_ai_requests: int | None


@dataclass(frozen=True)
class RepairProposal:
    event_id: Any
    headline: str
    old_country: str | None
    old_admin1: str | None
    old_disease: Any
    proposed_country: str | None
    proposed_admin1: str | None
    proposed_disease: Any
    proposed_event_type: EventType | None
    country_source: str
    admin1_source: str
    disease_source: str


@dataclass(frozen=True)
class RepairResult:
    examined: int = 0
    existing_extraction_reused: int = 0
    reextracted: int = 0
    ai_requests: int = 0
    expanded_retries: int = 0
    ai_cost_usd: Decimal = Decimal("0")
    country_resolved: int = 0
    admin1_resolved: int = 0
    disease_resolved: int = 0
    event_type_resolved: int = 0
    still_unresolved: int = 0
    conflicts: int = 0
    proposals: tuple[RepairProposal, ...] = ()


def parse_arguments(argv: Sequence[str]) -> Arguments:
    parser = argparse.ArgumentParser(
        prog="metadata:repair-ai",
        description="Recover missing event metadata through normal AI extraction.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview changes without writing.")
    mode.add_argument("--apply", action="store_true", help="Write approved metadata in place.")
    parser.add_argument(
        "--enforce-read-only",
        action="store_true",
        help="Set and verify PostgreSQL transaction read-only mode.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Events to examine.")
    parser.add_argument("--max-ai-requests", type=int, default=None)
    clean_argv = [argument for argument in argv if argument != "--"]
    parsed = parser.parse_args(clean_argv)
    if parsed.apply and parsed.enforce_read_only:
        parser.error("--apply cannot be combined with --enforce-read-only")
    return Arguments(
        apply=parsed.apply,
        enforce_read_only=parsed.enforce_read_only,
        limit=parsed.limit,
        max_ai_requests=parsed.max_ai_requests,
    )


def _extractable_signal(signal: Any) -> ExtractableSignal | None:
    content = getattr(signal, "raw_text", None)
    if not content:
        return None
    return ExtractableSignal(
        id=signal.id,
        title=signal.title,
        raw_text=content,
    )


def _metadata_can_be_reused(
    evidence: MetadataEvidence,
    event: Any,
    resolver: LocalMetadataResolver,
) -> bool:
    # Triage fields are retained as historical evidence, never as a reason to
    # skip extraction. Only a complete, currently valid extraction can be
    # reused by metadata repair.
    if evidence.extraction is None:
        return False
    resolved = resolver.resolve(evidence)
    fields = evidence.extraction
    validated = resolver.validate_metadata(fields)
    if any(
        raw is not None and normalized is None
        for raw, normalized in (
            (fields.disease, validated.disease_id),
            (fields.country, validated.country_code),
            (fields.admin1, validated.admin1),
        )
    ):
        return False
    if event.country_code is None and resolved.country_code is None:
        return False
    return not (event.disease_id is None and resolved.disease_id is None)


def _apply_extraction(
    evidence: MetadataEvidence,
    result: ExtractionSignalResult,
) -> MetadataEvidence:
    if result.extraction is None:
        return evidence
    return MetadataEvidence(
        title=evidence.title,
        text=evidence.text,
        extraction=metadata_fields_from_extraction(result.extraction),
        triage=evidence.triage,
    )


def _proposal(
    event: Any,
    patch: Any,
    resolved: ResolvedMetadata,
) -> RepairProposal:
    return RepairProposal(
        event_id=event.id,
        headline=str(getattr(event, "headline", None) or getattr(event, "title", "") or ""),
        old_country=event.country_code,
        old_admin1=event.admin1,
        old_disease=event.disease_id,
        proposed_country=patch.country_code,
        proposed_admin1=patch.admin1,
        proposed_disease=patch.disease_id,
        proposed_event_type=patch.event_type,
        country_source=resolved.country_source,
        admin1_source=resolved.admin1_source,
        disease_source=resolved.disease_source,
    )


def run_repair_ai(
    session: Session,
    repository: AiRepository,
    model: ChatModel,
    resolver: LocalMetadataResolver,
    *,
    apply: bool,
    limit: int | None,
    max_ai_requests: int,
    max_cost_usd: Decimal,
    max_tier: int,
    max_input_characters: int = DEFAULT_MAX_INPUT_CHARACTERS,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    now: datetime | None = None,
) -> RepairResult:
    statement = (
        select(Event)
        .where(or_(Event.country_code.is_(None), Event.disease_id.is_(None)))
        .order_by(Event.created_at, Event.id)
    )
    if limit is not None:
        statement = statement.limit(limit)
    events = session.execute(statement).scalars().all()
    ladder = build_extraction_ladder(repository, max_tier=max_tier)
    budget = RunBudget(Guards(max_requests=max_ai_requests, max_cost_usd=max_cost_usd))
    moment = now or datetime.now(UTC)
    proposals: list[RepairProposal] = []
    existing_extraction_reused = reextracted = requests = expanded_retries = conflicts = 0
    ai_cost_usd = Decimal("0")
    country_resolved = admin1_resolved = disease_resolved = event_type_resolved = 0
    still_unresolved = 0
    examined = 0

    for event in events:
        examined += 1
        rows = session.execute(
            select(Signal, Source.name)
            .join(EventSignal, EventSignal.signal_id == Signal.id)
            .join(Source, Source.id == Signal.source_id)
            .where(EventSignal.event_id == event.id)
            .order_by(EventSignal.is_primary.desc(), Signal.first_seen_at, Signal.id)
        ).all()
        eligible_rows = [signal for signal, _ in rows if signal.public_health_relevant is not False]
        evidence_list: list[MetadataEvidence] = []
        for signal, _source_name in rows:
            if signal.public_health_relevant is False:
                continue
            evidence = metadata_evidence_for_signal(
                signal, read_stored_extraction(signal.ai_extraction)
            )
            if _metadata_can_be_reused(evidence, event, resolver):
                existing_extraction_reused += 1
            else:
                extractable = _extractable_signal(signal)
                if extractable is None:
                    evidence_list.append(evidence)
                    continue
                reextracted += 1
                result = extract_signal(
                    extractable,
                    model,
                    ladder=ladder,
                    budget=budget,
                    max_input_characters=max_input_characters,
                    min_confidence=min_confidence,
                )
                requests += len(result.attempts)
                expanded_retries += result.expanded_retries
                ai_cost_usd += sum((attempt.cost for attempt in result.attempts), Decimal("0"))
                evidence = _apply_extraction(evidence, result)
                if apply:
                    for attempt in result.attempts:
                        repository.record_request(
                            cost_row(
                                attempt,
                                purpose=AiPurpose.EXTRACTION,
                                signal_id=signal.id,
                                batch_size=1,
                                at=moment,
                            )
                        )
                    if result.extraction is not None:
                        disease_id = (
                            repository.resolve_disease(result.extraction.disease.name)
                            if result.extraction.disease is not None
                            else None
                        )
                        repository.record_extraction(
                            signal.id,
                            StoredExtraction(
                                extraction=result.extraction,
                                disease_id=disease_id,
                                model_id=result.attempts[-1].spec.model_id,
                                processed_at=moment,
                            ),
                        )
            evidence_list.append(evidence)
            if budget.exhausted and len(evidence_list) < len(eligible_rows):
                break

        # Do not reconcile an event from a partial linked-signal set after a
        # request guard trips; an unseen contradictory source must remain able
        # to veto the proposal on a later bounded run.
        if budget.exhausted and len(evidence_list) < len(eligible_rows):
            break

        resolved = resolve_repair_evidence(evidence_list, resolver)
        repair_event = MetadataRepairEvent(
            event_id=event.id,
            country_code=event.country_code,
            admin1=event.admin1,
            disease_id=event.disease_id,
            event_type=event.event_type,
            signals=tuple(evidence_list),
        )
        patch = repair_event_metadata(repair_event, resolver)
        conflicts += len(resolved.conflicts)
        country_resolved += int(patch.country_code is not None)
        admin1_resolved += int(patch.admin1 is not None)
        disease_resolved += int(patch.disease_id is not None)
        event_type_resolved += int(patch.event_type is not None)
        final_country = event.country_code or patch.country_code
        final_disease = event.disease_id or patch.disease_id
        still_unresolved += int(final_country is None or final_disease is None)
        if patch.changed:
            proposals.append(_proposal(event, patch, resolved))
            if apply:
                values = {
                    key: value
                    for key, value in {
                        "country_code": patch.country_code,
                        "admin1": patch.admin1,
                        "disease_id": patch.disease_id,
                        "event_type": patch.event_type,
                    }.items()
                    if value is not None
                }
                session.execute(update(Event).where(Event.id == event.id).values(**values))
        if budget.exhausted:
            break

    if apply:
        session.commit()
    return RepairResult(
        examined=examined,
        existing_extraction_reused=existing_extraction_reused,
        reextracted=reextracted,
        ai_requests=requests,
        expanded_retries=expanded_retries,
        ai_cost_usd=ai_cost_usd,
        country_resolved=country_resolved,
        admin1_resolved=admin1_resolved,
        disease_resolved=disease_resolved,
        event_type_resolved=event_type_resolved,
        still_unresolved=still_unresolved,
        conflicts=conflicts,
        proposals=tuple(proposals),
    )


def _run(arguments: Arguments) -> RepairResult:
    from episignal_backend.ai.repository import SqlAlchemyAiRepository
    from episignal_backend.ai.routing import NoProviderKey, routed_from_settings
    from episignal_backend.config import get_settings

    settings = get_settings()
    with session_scope() as session:
        if arguments.enforce_read_only:
            enforce_read_only_transaction(session)
        repository = SqlAlchemyAiRepository(session)
        try:
            model = routed_from_settings(settings, list(repository.models()))
        except NoProviderKey as error:
            raise RuntimeError(str(error)) from error
        return run_repair_ai(
            session,
            repository,
            model,
            local_metadata_resolver(session),
            apply=arguments.apply,
            limit=arguments.limit,
            max_ai_requests=arguments.max_ai_requests or settings.ai_max_requests_per_run,
            max_cost_usd=settings.ai_max_cost_usd_per_run,
            max_tier=settings.ai_max_tier,
            max_input_characters=settings.ai_max_input_characters,
            min_confidence=settings.ai_min_confidence,
        )


def _print_proposal(proposal: RepairProposal) -> None:
    print(f"EVENT {proposal.event_id}\n{proposal.headline}")
    print(
        f"OLD: country={proposal.old_country} admin1={proposal.old_admin1} "
        f"disease={proposal.old_disease}"
    )
    print(
        "PROPOSED: "
        f"country={proposal.proposed_country} admin1={proposal.proposed_admin1} "
        f"disease={proposal.proposed_disease} event_type={proposal.proposed_event_type}"
    )
    print(
        "SOURCE: "
        f"country_source={proposal.country_source} admin1_source={proposal.admin1_source} "
        f"disease_source={proposal.disease_source}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        result = _run(arguments)
    except Exception as error:
        print(
            f"AI metadata repair failed before completing ({type(error).__name__}).",
            file=sys.stderr,
        )
        return 1
    print(
        f"examined={result.examined} "
        f"existing_extraction_reused={result.existing_extraction_reused} "
        f"reextracted={result.reextracted} expanded_retries={result.expanded_retries} "
        f"ai_requests={result.ai_requests} "
        f"ai_cost_usd={result.ai_cost_usd} "
        f"country_resolved={result.country_resolved} "
        f"admin1_resolved={result.admin1_resolved} "
        f"disease_resolved={result.disease_resolved} "
        f"event_type_resolved={result.event_type_resolved} "
        f"still_unresolved={result.still_unresolved} conflicts={result.conflicts}"
    )
    for proposal in result.proposals[:20]:
        _print_proposal(proposal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
