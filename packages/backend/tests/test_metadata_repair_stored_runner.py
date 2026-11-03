from types import SimpleNamespace
from uuid import UUID

from episignal_backend.metadata import LocalMetadataResolver, MetadataEvidence, MetadataFields
from episignal_backend.metadata_repair_stored_runner import (
    parse_arguments,
    stored_repair_proposal,
)


def resolver() -> LocalMetadataResolver:
    return LocalMetadataResolver(
        country_aliases={"bangladesh": "BD", "singapore": "SG"},
        country_codes={"BD", "SG"},
    )


def event(**overrides: object) -> SimpleNamespace:
    values = {
        "id": UUID("00000000-0000-0000-0000-000000000001"),
        "public_id": "EVT-EXPLICIT",
        "country_code": None,
        "admin1": None,
        "disease_id": None,
        "event_type": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_stored_repair_requires_explicit_ids_and_defaults_to_dry_run() -> None:
    arguments = parse_arguments(["--public-id", "EVT-ONE", "--public-id", "EVT-ONE"])

    assert arguments.public_ids == ("EVT-ONE",)
    assert arguments.apply is False


def test_stored_repair_reconciles_only_supplied_extraction_evidence() -> None:
    proposal = stored_repair_proposal(
        event(),
        [
            MetadataEvidence(
                title="Dengue campaign",
                text="",
                extraction=MetadataFields(country="Bangladesh"),
            ),
            MetadataEvidence(
                title="Dhaka dengue campaign",
                text="",
                extraction=MetadataFields(country="Bangladesh", place_name="Dhaka"),
            ),
        ],
        resolver(),
    )

    assert proposal is not None
    assert proposal.proposed_country == "BD"


def test_stored_repair_never_majority_votes_cross_country_evidence() -> None:
    proposal = stored_repair_proposal(
        event(),
        [
            MetadataEvidence(
                title="Thailand report",
                text="",
                extraction=MetadataFields(country="Thailand"),
            ),
            MetadataEvidence(
                title="Thailand report",
                text="",
                extraction=MetadataFields(country="Thailand"),
            ),
            MetadataEvidence(
                title="Singapore report",
                text="",
                extraction=MetadataFields(country="Singapore"),
            ),
        ],
        LocalMetadataResolver(
            country_aliases={"thailand": "TH", "singapore": "SG"},
            country_codes={"TH", "SG"},
        ),
    )

    assert proposal is None
