import json
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from episignal_backend.historical_disease_repair import (
    APPROVED_DISEASES,
    build_repair_candidate,
    historical_signal_statement,
    parse_arguments,
    repair_update_statement,
)
from sqlalchemy.dialects import postgresql

RABIES_ID = uuid4()
WEST_NILE_ID = uuid4()
AVIAN_INFLUENZA_ID = uuid4()
OTHER_DISEASE_ID = uuid4()


def exact_resolver(value: str) -> UUID | None:
    values = {
        "rabies": RABIES_ID,
        "west nile virus": WEST_NILE_ID,
        "h5 bird flu": AVIAN_INFLUENZA_ID,
        "salmonella": OTHER_DISEASE_ID,
        "meningitis": OTHER_DISEASE_ID,
    }
    return values.get(" ".join(value.split()).casefold())


def approved_diseases() -> Mapping[UUID, str]:
    return {
        RABIES_ID: APPROVED_DISEASES["rabies"],
        WEST_NILE_ID: APPROVED_DISEASES["west-nile-virus-disease"],
        AVIAN_INFLUENZA_ID: APPROVED_DISEASES["avian-influenza"],
    }


@pytest.mark.parametrize(
    ("current", "old", "expected_id", "expected_name"),
    [
        ("rabies", None, RABIES_ID, "Rabies"),
        ("Rabies", None, RABIES_ID, "Rabies"),
        ("West Nile virus", None, WEST_NILE_ID, "West Nile virus disease"),
        ("WEST NILE VIRUS", None, WEST_NILE_ID, "West Nile virus disease"),
        ("H5 bird flu", None, AVIAN_INFLUENZA_ID, "Avian influenza"),
        (None, "Rabies", RABIES_ID, "Rabies"),
        (None, "WEST NILE VIRUS", WEST_NILE_ID, "West Nile virus disease"),
        (None, "h5 BIRD FLU", AVIAN_INFLUENZA_ID, "Avian influenza"),
        ("   ", "Rabies", RABIES_ID, "Rabies"),
    ],
)
def test_current_and_old_extraction_schemas_repair_only_approved_exact_matches(
    current: str | None,
    old: str | None,
    expected_id: UUID,
    expected_name: str,
) -> None:
    candidate = build_repair_candidate(
        signal_id=uuid4(),
        existing_disease_id=None,
        current_disease_text=current,
        old_disease_text=old,
        resolve_disease=exact_resolver,
        approved_diseases=approved_diseases(),
    )

    assert candidate is not None
    assert candidate.proposed_disease_id == expected_id
    assert candidate.resolved_canonical_name == expected_name


@pytest.mark.parametrize(
    "disease_text",
    [
        "Salmonella",
        "meningitis",
        "Chikungunya and Dengue",
        "West Nile virus and Cache Valley virus",
        "unknown disease text",
        None,
    ],
)
def test_unapproved_or_non_exact_disease_text_is_not_repaired(disease_text: str | None) -> None:
    assert (
        build_repair_candidate(
            signal_id=uuid4(),
            existing_disease_id=None,
            current_disease_text=disease_text,
            old_disease_text=None,
            resolve_disease=exact_resolver,
            approved_diseases=approved_diseases(),
        )
        is None
    )


def test_conflicting_current_and_old_values_are_not_repaired() -> None:
    assert (
        build_repair_candidate(
            signal_id=uuid4(),
            existing_disease_id=None,
            current_disease_text="rabies",
            old_disease_text="West Nile virus",
            resolve_disease=exact_resolver,
            approved_diseases=approved_diseases(),
        )
        is None
    )


def test_existing_disease_id_is_never_repaired() -> None:
    assert (
        build_repair_candidate(
            signal_id=uuid4(),
            existing_disease_id=uuid4(),
            current_disease_text="rabies",
            old_disease_text=None,
            resolve_disease=exact_resolver,
            approved_diseases=approved_diseases(),
        )
        is None
    )


def test_repair_update_rechecks_null_disease_id() -> None:
    candidate = build_repair_candidate(
        signal_id=uuid4(),
        existing_disease_id=None,
        current_disease_text="rabies",
        old_disease_text=None,
        resolve_disease=exact_resolver,
        approved_diseases=approved_diseases(),
    )
    assert candidate is not None

    sql = str(
        repair_update_statement(candidate).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert "signals.disease_id IS NULL" in sql
    assert "UPDATE signals" in sql
    assert "events" not in sql


def test_candidate_selection_reads_current_and_old_extraction_paths() -> None:
    sql = str(
        historical_signal_statement().compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )

    assert "ai_extraction ->> 'disease_text'" in sql
    assert "ai_extraction['disease'] ->> 'name'" in sql
    assert "signals.disease_id IS NULL" in sql


def test_dry_run_is_default_and_apply_is_explicit() -> None:
    assert parse_arguments([]).apply is False
    assert parse_arguments(["--dry-run"]).apply is False
    assert parse_arguments(["--apply"]).apply is True


def test_broad_requeue_flag_is_not_supported() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["--requeue-existing"])


def test_only_historical_disease_repair_command_is_exposed() -> None:
    package_json = json.loads(
        (Path(__file__).parents[3] / "package.json").read_text(encoding="utf-8")
    )

    assert package_json["scripts"]["repair:historical-diseases"].endswith(
        "-m episignal_backend.historical_disease_repair"
    )
