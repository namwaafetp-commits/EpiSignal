import json
from pathlib import Path
from uuid import uuid4

import pytest
from episignal_backend.historical_event_disease_repair import (
    APPROVED_CANONICAL_NAMES,
    build_event_repair_candidate,
    eligible_event_statement,
    event_repair_statement,
    parse_arguments,
    run_repair,
)
from sqlalchemy.dialects import postgresql

RABIES_ID = uuid4()
WEST_NILE_ID = uuid4()
AVIAN_INFLUENZA_ID = uuid4()
OTHER_DISEASE_ID = uuid4()
SIGNAL_ID = uuid4()
EVENT_ID = uuid4()


def candidate(
    *,
    event_disease_id=None,
    attached_signal_count=1,
    signal_disease_id=RABIES_ID,
    signal_id=SIGNAL_ID,
    canonical_name="Rabies",
    approved_signal_ids=(SIGNAL_ID,),
    approved_disease_ids=(RABIES_ID, WEST_NILE_ID, AVIAN_INFLUENZA_ID),
):
    return build_event_repair_candidate(
        event_id=EVENT_ID,
        signal_id=signal_id,
        current_event_disease_id=event_disease_id,
        attached_signal_count=attached_signal_count,
        signal_disease_id=signal_disease_id,
        canonical_name=canonical_name,
        approved_signal_ids=approved_signal_ids,
        approved_disease_ids=approved_disease_ids,
    )


@pytest.mark.parametrize(
    ("canonical_name", "disease_id"),
    [
        ("Rabies", RABIES_ID),
        ("West Nile virus disease", WEST_NILE_ID),
        ("Avian influenza", AVIAN_INFLUENZA_ID),
    ],
)
def test_only_one_signal_with_approved_repaired_disease_is_eligible(
    canonical_name, disease_id
) -> None:
    assert (
        candidate(
            signal_disease_id=disease_id,
            signal_id=SIGNAL_ID,
            canonical_name=canonical_name,
        )
        is not None
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_disease_id", uuid4()),
        ("attached_signal_count", 0),
        ("attached_signal_count", 2),
        ("signal_disease_id", None),
        ("signal_disease_id", OTHER_DISEASE_ID),
        ("canonical_name", "Salmonella"),
        ("signal_id", uuid4()),
    ],
)
def test_scope_exclusions_are_not_eligible(field, value) -> None:
    values = {field: value}
    assert candidate(**values) is None


def test_cli_defaults_to_dry_run_and_requires_explicit_apply() -> None:
    assert parse_arguments([]).apply is False
    assert parse_arguments(["--dry-run"]).apply is False
    assert parse_arguments(["--apply"]).apply is True


def test_broad_requeue_flag_is_not_supported() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["--requeue-existing"])


def test_eligible_query_uses_approved_scope_and_exactly_one_signal() -> None:
    sql = str(
        eligible_event_statement(
            approved_signal_ids=(SIGNAL_ID,),
            approved_disease_ids=(RABIES_ID,),
        ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    assert "UPDATE" not in sql
    assert "events.disease_id IS NULL" in sql
    assert "signal_id IN" in sql
    assert "NOT (EXISTS" in sql
    assert "signals.disease_id IS NOT NULL" in sql
    assert "diseases.canonical_name IN" in sql


def test_update_rechecks_event_signal_cardinality_and_signal_disease() -> None:
    repair = candidate()
    assert repair is not None
    sql = str(
        event_repair_statement(repair).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert "UPDATE events" in sql
    assert "events.disease_id IS NULL" in sql
    assert "signals.disease_id" in sql
    assert "event_signals" in sql
    assert "signals" in sql
    assert "count" not in sql
    assert "UPDATE signals" not in sql
    assert "UPDATE event_signals" not in sql


class FakeResult:
    def __init__(self, rowcount: int = 0) -> None:
        self.rowcount = rowcount


class FakeSession:
    def __init__(self, rowcounts: list[int] | None = None) -> None:
        self.rowcounts = iter(rowcounts or [])
        self.executed = []

    def execute(self, statement):
        self.executed.append(statement)
        return FakeResult(next(self.rowcounts, 0))


def test_dry_run_performs_no_update(monkeypatch) -> None:
    repair = candidate()
    assert repair is not None
    session = FakeSession()
    monkeypatch.setattr(
        "episignal_backend.historical_event_disease_repair.find_repair_candidates",
        lambda _session: (repair,),
    )

    result = run_repair(session, apply=False)

    assert result.candidates == (repair,)
    assert result.applied == 0
    assert result.skipped == 0
    assert session.executed == []


def test_concurrent_recheck_skips_changed_event(monkeypatch) -> None:
    repair = candidate()
    assert repair is not None
    session = FakeSession([0])
    monkeypatch.setattr(
        "episignal_backend.historical_event_disease_repair.find_repair_candidates",
        lambda _session: (repair,),
    )

    result = run_repair(session, apply=True)

    assert result.applied == 0
    assert result.skipped == 1


def test_second_run_after_apply_has_no_candidates(monkeypatch) -> None:
    repair = candidate()
    assert repair is not None
    session = FakeSession([1])
    candidates = [(repair,), ()]
    monkeypatch.setattr(
        "episignal_backend.historical_event_disease_repair.find_repair_candidates",
        lambda _session: candidates.pop(0),
    )

    first = run_repair(session, apply=True)
    second = run_repair(session, apply=True)

    assert first.applied == 1
    assert second.candidates == ()
    assert second.applied == 0


def test_command_script_is_exposed() -> None:
    package_json = json.loads(
        (Path(__file__).parents[3] / "package.json").read_text(encoding="utf-8")
    )

    assert package_json["scripts"]["repair:historical-event-diseases"].endswith(
        "-m episignal_backend.historical_event_disease_repair"
    )


def test_approved_canonical_names_are_exact() -> None:
    assert {
        "Rabies",
        "West Nile virus disease",
        "Avian influenza",
    } == APPROVED_CANONICAL_NAMES
