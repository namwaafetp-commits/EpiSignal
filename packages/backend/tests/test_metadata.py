from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from episignal_backend.metadata import (
    Admin1VocabularyEntry,
    DiseaseVocabularyEntry,
    LocalMetadataResolver,
    MetadataEvidence,
    MetadataFields,
    MetadataRepairEvent,
    repair_event_metadata,
)
from episignal_backend.metadata_repair_runner import parse_arguments, run_repair

MEASLES = UUID("00000000-0000-0000-0000-000000000001")
MALARIA = UUID("00000000-0000-0000-0000-000000000002")
EBOLA = UUID("00000000-0000-0000-0000-000000000003")
AVIAN_INFLUENZA = UUID("00000000-0000-0000-0000-000000000004")


def resolver() -> LocalMetadataResolver:
    return LocalMetadataResolver(
        country_aliases={
            "south africa": "ZA",
            "india": "IN",
            "democratic republic of the congo": "CD",
            "drc": "CD",
            "australia": "AU",
            "uganda": "UG",
            "kenya": "KE",
            "united states": "US",
        },
        country_codes={"ZA", "IN", "CD", "AU", "UG", "KE", "US"},
        diseases=(
            DiseaseVocabularyEntry(MEASLES, "Measles", "measles", ("rubeola",)),
            DiseaseVocabularyEntry(MALARIA, "Malaria", "malaria", ()),
            DiseaseVocabularyEntry(EBOLA, "Ebola virus disease", "ebola-virus-disease", ("Ebola",)),
            DiseaseVocabularyEntry(
                AVIAN_INFLUENZA,
                "Avian influenza",
                "avian-influenza",
                ("bird flu", "H5N1"),
            ),
        ),
        admin1s=(
            Admin1VocabularyEntry("Wisconsin", "US", "WI"),
            Admin1VocabularyEntry("Arizona", "US", "AZ"),
            Admin1VocabularyEntry("Springfield", "US", "IL"),
            Admin1VocabularyEntry("Springfield", "AU", "NSW"),
        ),
    )


@pytest.mark.parametrize(
    ("title", "disease_id", "country_code"),
    [
        ("South Africa measles outbreak exceeds 3,400 confirmed cases", MEASLES, "ZA"),
        ("India's malaria cases and deaths drop nearly 80%", MALARIA, "IN"),
        ("Ebola outbreak in eastern DRC spreads to two new health zones", EBOLA, "CD"),
        ("H5N1 bird flu established across Australia", AVIAN_INFLUENZA, "AU"),
    ],
)
def test_explicit_headline_metadata_resolves_without_model_output(
    title: str, disease_id: UUID, country_code: str
) -> None:
    resolved = resolver().resolve(MetadataEvidence(title=title, text=""))

    assert resolved.disease_id == disease_id
    assert resolved.country_code == country_code


def test_unique_admin1_in_headline_supplies_country_and_admin1_code() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(title="Measles Outbreak Grows to 98 Cases in Wisconsin", text="")
    )

    assert resolved.disease_id == MEASLES
    assert resolved.country_code == "US"
    assert resolved.admin1 == "WI"


def test_ambiguous_admin1_stays_unresolved() -> None:
    resolved = resolver().resolve(MetadataEvidence(title="Springfield outbreak report", text=""))

    assert resolved.country_code is None
    assert resolved.admin1 is None


def test_ambiguous_generic_country_name_stays_unresolved() -> None:
    resolved = resolver().resolve(MetadataEvidence(title="Congo outbreak report", text=""))

    assert resolved.country_code is None


def test_extraction_metadata_wins_over_deterministic_headline_fallback() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="South Africa measles outbreak",
            text="",
            extraction=MetadataFields(disease="malaria", country="IN"),
        )
    )

    assert resolved.disease_id == MALARIA
    assert resolved.country_code == "IN"


def test_invalid_extraction_disease_falls_through_to_triage() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="Measles outbreak",
            text="",
            extraction=MetadataFields(disease="not in reviewed vocabulary"),
            triage=MetadataFields(disease="malaria", country="IN"),
        )
    )

    assert resolved.disease_id == MALARIA
    assert resolved.country_code == "IN"


def test_unknown_two_letter_country_code_stays_unresolved() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(title="Outbreak report", text="", triage=MetadataFields(country="ZZ"))
    )

    assert resolved.country_code is None


def test_triage_location_wins_when_extraction_has_no_location() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="Measles outbreak",
            text="",
            extraction=MetadataFields(disease="measles"),
            triage=MetadataFields(country="KE", admin1="Nairobi"),
        )
    )

    assert resolved.disease_id == MEASLES
    assert resolved.country_code == "KE"
    assert resolved.admin1 is None


def test_extracted_place_name_can_resolve_a_unique_admin1() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="Measles outbreak",
            text="",
            extraction=MetadataFields(place_name="Wisconsin"),
        )
    )

    assert resolved.country_code == "US"
    assert resolved.admin1 == "WI"


def test_fallback_reads_title_and_body_but_does_not_guess() -> None:
    known = resolver().resolve(
        MetadataEvidence(title="A report", text="Officials in Arizona reported malaria.")
    )
    ambiguous = resolver().resolve(
        MetadataEvidence(title="A report", text="Officials reported an outbreak in Springfield.")
    )

    assert known.disease_id == MALARIA
    assert known.country_code == "US"
    assert known.admin1 == "AZ"
    assert ambiguous.country_code is None
    assert ambiguous.admin1 is None


def test_repair_patch_only_fills_missing_event_fields() -> None:
    patch = repair_event_metadata(
        MetadataRepairEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000010"),
            country_code=None,
            admin1=None,
            disease_id=None,
            signals=(
                MetadataEvidence(
                    title="South Africa measles outbreak exceeds 3,400 confirmed cases",
                    text="",
                ),
            ),
        ),
        resolver(),
    )

    assert patch.country_code == "ZA"
    assert patch.disease_id == MEASLES
    assert patch.admin1 is None


def test_metadata_repair_defaults_to_dry_run() -> None:
    assert parse_arguments([]).apply is False
    assert parse_arguments(["--dry-run"]).apply is False
    assert parse_arguments(["--apply"]).apply is True


class RepairResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalars(self) -> "RepairResult":
        return self

    def all(self) -> Any:
        return self.value


class RepairSession:
    def __init__(self, event: Any, signal: Any) -> None:
        self.results = [RepairResult([event]), RepairResult([(signal, True)])]
        self.executed: list[Any] = []
        self.commits = 0

    def execute(self, statement: Any) -> RepairResult:
        self.executed.append(statement)
        return self.results.pop(0) if self.results else RepairResult([])

    def commit(self) -> None:
        self.commits += 1


def test_repair_runner_updates_existing_event_only_when_apply_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import episignal_backend.metadata_repair_runner as repair_runner

    event = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000011"),
        country_code=None,
        admin1=None,
        disease_id=None,
    )
    signal = SimpleNamespace(
        id=UUID("00000000-0000-0000-0000-000000000012"),
        title="South Africa measles outbreak",
        raw_text="Officials reported an outbreak.",
        ai_extraction=None,
        triage_disease_text=None,
        triage_country_code=None,
        triage_admin1=None,
        triage_admin2=None,
        triage_location_text=None,
    )
    monkeypatch.setattr(repair_runner, "local_metadata_resolver", lambda session: resolver())

    dry_run = RepairSession(event, signal)
    result = run_repair(dry_run, apply=False)
    assert result.country_resolved == 1
    assert result.disease_resolved == 1
    assert dry_run.commits == 0
    assert len(dry_run.executed) == 2

    apply_run = RepairSession(event, signal)
    run_repair(apply_run, apply=True)
    assert apply_run.commits == 1
    assert len(apply_run.executed) == 3
