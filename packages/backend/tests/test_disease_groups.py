import json
from pathlib import Path

from episignal_backend.disease_groups import (
    CANONICAL_DISEASE_GROUPS,
    DISEASE_GROUP_LABELS,
    DiseaseGroup,
    disease_group_for,
    disease_group_label,
)

SEED_PATH = Path(__file__).parents[3] / "database" / "seeds" / "diseases.json"


def seeded_disease_slugs() -> set[str]:
    return {row["slug"] for row in json.loads(SEED_PATH.read_text())}


def test_every_seeded_canonical_disease_has_exactly_one_group() -> None:
    assert set(CANONICAL_DISEASE_GROUPS) == seeded_disease_slugs()
    assert all(isinstance(group, DiseaseGroup) for group in CANONICAL_DISEASE_GROUPS.values())


def test_aliases_are_grouped_after_canonical_resolution() -> None:
    # The database resolver maps this alias to the canonical `dengue` row;
    # grouping consumes that canonical slug, never the alias text.
    assert disease_group_for("dengue") is DiseaseGroup.VECTOR_BORNE
    assert disease_group_for("dengue fever") is DiseaseGroup.UNKNOWN


def test_unknown_disease_safely_uses_unknown_group() -> None:
    assert disease_group_for(None) is DiseaseGroup.UNKNOWN
    assert disease_group_for("new-unreviewed-disease") is DiseaseGroup.UNKNOWN


def test_group_labels_are_stable_and_complete() -> None:
    assert set(DISEASE_GROUP_LABELS) == set(DiseaseGroup)
    assert disease_group_label(DiseaseGroup.ENTERIC_FOOD_WATERBORNE) == (
        "Enteric / food- & water-borne infections"
    )
    assert disease_group_label(DiseaseGroup.UNKNOWN) == "Unknown / unclassified"
