from uuid import UUID

import pytest
from episignal_backend.db.types import EventType
from episignal_backend.metadata import (
    Admin1VocabularyEntry,
    DiseaseVocabularyEntry,
    LocalMetadataResolver,
    MetadataEvidence,
    MetadataFields,
    MetadataRepairEvent,
    repair_event_metadata,
)
from episignal_backend.metadata_repair_ai_runner import _metadata_can_be_reused

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
            Admin1VocabularyEntry("New Mexico", "US", "NM"),
            Admin1VocabularyEntry("Niger State", "NG", "NI"),
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
def test_unstructured_headline_metadata_stays_unresolved(
    title: str, disease_id: UUID, country_code: str
) -> None:
    resolved = resolver().resolve(MetadataEvidence(title=title, text=""))

    assert resolved.disease_id is None
    assert resolved.country_code is None


def test_structured_admin1_is_validated_against_country() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="Measles Outbreak Grows to 98 Cases in Wisconsin",
            text="",
            extraction=MetadataFields(disease="measles", country="US", admin1="Wisconsin"),
        )
    )

    assert resolved.disease_id == MEASLES
    assert resolved.country_code == "US"
    assert resolved.admin1 == "WI"


@pytest.mark.parametrize(
    ("title", "country_code", "admin1"),
    [
        ("New Mexico measles outbreak", "US", "New Mexico"),
        ("Diphtheria outbreak in Niger State", "NG", "Niger State"),
    ],
)
def test_specific_admin1_wins_over_contained_country_alias(
    title: str, country_code: str, admin1: str
) -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title=title,
            text="",
            extraction=MetadataFields(country=country_code, admin1=admin1),
        )
    )

    assert resolved.country_code == country_code
    assert resolved.admin1 == {"New Mexico": "NM", "Niger State": "NI"}[admin1]


def test_conflicting_country_and_admin1_evidence_stays_unresolved() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="New Mexico, Mexico measles outbreak",
            text="",
            extraction=MetadataFields(country="MX", admin1="New Mexico"),
        )
    )

    assert resolved.country_code == "MX"
    assert resolved.admin1 is None


def test_invalid_admin1_rejects_location_metadata() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="Unknown province measles outbreak",
            text="",
            extraction=MetadataFields(country="US", admin1="Unknown Province"),
        )
    )

    assert resolved.country_code == "US"
    assert resolved.admin1 is None


def test_valid_disease_survives_invalid_admin1() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="Measles outbreak",
            text="",
            extraction=MetadataFields(disease="measles", country="US", admin1="Unknown Province"),
        )
    )

    assert resolved.disease_id == MEASLES
    assert resolved.disease_text == "Measles"
    assert resolved.country_code == "US"
    assert resolved.admin1 is None


def test_unknown_disease_preserves_exact_normalized_text() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="Meningococcal disease outbreak",
            text="",
            extraction=MetadataFields(
                disease="  Meningococcal   disease ", country="United States"
            ),
        )
    )

    assert resolved.disease_id is None
    assert resolved.disease_text == "meningococcal disease"
    assert resolved.country_code == "US"


def test_structured_country_conflicting_with_admin1_stays_unresolved() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="New Mexico measles outbreak",
            text="",
            extraction=MetadataFields(country="MX", admin1="New Mexico"),
        )
    )

    assert resolved.country_code == "MX"
    assert resolved.admin1 is None


def test_country_aliases_are_normalized_only_from_structured_fields() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="The US lab reported a measles outbreak",
            text="",
            extraction=MetadataFields(country="United States"),
        )
    )

    assert resolved.country_code == "US"


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


def test_invalid_extraction_disease_stays_unresolved() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="Measles outbreak",
            text="",
            extraction=MetadataFields(disease="not in reviewed vocabulary"),
            triage=MetadataFields(disease="malaria", country="IN"),
        )
    )

    assert resolved.disease_id is None
    assert resolved.country_code is None


def test_unknown_two_letter_country_code_stays_unresolved() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(title="Outbreak report", text="", extraction=MetadataFields(country="ZZ"))
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
    assert resolved.country_code is None
    assert resolved.admin1 is None


def test_unstructured_place_name_is_not_resolved_without_model_country_and_admin1() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="Measles outbreak",
            text="",
            extraction=MetadataFields(place_name="Wisconsin"),
        )
    )

    assert resolved.country_code is None
    assert resolved.admin1 is None


def test_article_text_is_never_scanned_for_metadata() -> None:
    known = resolver().resolve(
        MetadataEvidence(title="A report", text="Officials in Arizona reported malaria.")
    )
    ambiguous = resolver().resolve(
        MetadataEvidence(title="A report", text="Officials reported an outbreak in Springfield.")
    )

    assert known.disease_id is None
    assert known.country_code is None
    assert known.admin1 is None
    assert ambiguous.country_code is None
    assert ambiguous.admin1 is None


def test_resolved_metadata_exposes_field_provenance() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(
            title="ignored",
            text="ignored",
            extraction=MetadataFields(disease="measles", country="US"),
            triage=MetadataFields(disease="malaria", country="Canada"),
        )
    )

    assert resolved.disease_id == MEASLES
    assert resolved.country_code == "US"
    assert resolved.disease_source == "extraction"
    assert resolved.country_source == "extraction"
    assert resolved.conflicts == ()


def test_distinct_disease_names_of_different_lengths_stay_unresolved() -> None:
    resolved = resolver().resolve(
        MetadataEvidence(title="Measles and Ebola virus disease outbreak report", text="")
    )

    assert resolved.disease_id is None


def test_repair_does_not_infer_from_unstructured_headline() -> None:
    patch = repair_event_metadata(
        MetadataRepairEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000013"),
            country_code=None,
            admin1=None,
            disease_id=None,
            event_type=EventType.UNKNOWN_DISEASE_EVENT,
            signals=(MetadataEvidence(title="South Africa measles outbreak", text=""),),
        ),
        resolver(),
    )

    assert patch.disease_id is None
    assert patch.event_type is None


def test_repair_only_uses_validated_structured_metadata() -> None:
    patch = repair_event_metadata(
        MetadataRepairEvent(
            event_id=UUID("00000000-0000-0000-0000-000000000010"),
            country_code=None,
            admin1=None,
            disease_id=None,
            event_type=EventType.OTHER,
            signals=(
                MetadataEvidence(
                    title="South Africa measles outbreak exceeds 3,400 confirmed cases",
                    text="",
                ),
            ),
        ),
        resolver(),
    )

    assert patch.country_code is None
    assert patch.disease_id is None
    assert patch.admin1 is None


class IncompleteEvent:
    country_code = None
    disease_id = None


def test_metadata_repair_reextracts_when_country_exists_only_in_legacy_triage() -> None:
    evidence = MetadataEvidence(
        title="Measles outbreak",
        text="article",
        extraction=MetadataFields(disease="measles"),
        triage=MetadataFields(disease="measles", country="US"),
    )

    assert not _metadata_can_be_reused(evidence, IncompleteEvent(), resolver())


def test_metadata_repair_reextracts_when_disease_exists_only_in_legacy_triage() -> None:
    evidence = MetadataEvidence(
        title="Outbreak report",
        text="article",
        extraction=MetadataFields(country="US"),
        triage=MetadataFields(disease="measles", country="US"),
    )

    assert not _metadata_can_be_reused(evidence, IncompleteEvent(), resolver())


def test_metadata_repair_reuses_a_valid_extraction() -> None:
    evidence = MetadataEvidence(
        title="Measles outbreak",
        text="article",
        extraction=MetadataFields(disease="measles", country="US"),
        triage=MetadataFields(disease="malaria", country="IN"),
    )

    assert _metadata_can_be_reused(evidence, IncompleteEvent(), resolver())


def test_metadata_repair_reuses_valid_fields_when_admin1_is_invalid() -> None:
    evidence = MetadataEvidence(
        title="Measles outbreak",
        text="article",
        extraction=MetadataFields(disease="measles", country="US", admin1="Pennsylvania"),
    )

    assert _metadata_can_be_reused(evidence, IncompleteEvent(), resolver())


def test_metadata_repair_reuses_unknown_disease_text_for_diagnostics_and_grouping() -> None:
    evidence = MetadataEvidence(
        title="Meningococcal outbreak",
        text="article",
        extraction=MetadataFields(disease="Meningococcal disease", country="US"),
    )

    assert _metadata_can_be_reused(evidence, IncompleteEvent(), resolver())
