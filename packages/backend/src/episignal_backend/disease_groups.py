"""Deterministic EpiSignal standard surveillance grouping.

This is an EpiSignal product taxonomy, not an official WHO taxonomy. The
registry is keyed only by reviewed canonical disease slugs. Alias resolution
belongs to the disease vocabulary repository and must happen before lookup.
"""

from enum import StrEnum


class DiseaseGroup(StrEnum):
    RESPIRATORY = "respiratory"
    ENTERIC_FOOD_WATERBORNE = "enteric_food_waterborne"
    VECTOR_BORNE = "vector_borne"
    VACCINE_PREVENTABLE = "vaccine_preventable"
    VIRAL_HEMORRHAGIC_FEVER = "viral_hemorrhagic_fever"
    NEUROLOGIC_INVASIVE = "neurologic_invasive"
    BLOOD_BORNE_STI = "blood_borne_sti"
    HEALTHCARE_ASSOCIATED_AMR = "healthcare_associated_amr"
    OTHER_INFECTIOUS = "other_infectious"
    UNKNOWN = "unknown"


DISEASE_GROUP_LABELS: dict[DiseaseGroup, str] = {
    DiseaseGroup.RESPIRATORY: "Respiratory infections",
    DiseaseGroup.ENTERIC_FOOD_WATERBORNE: "Enteric / food- & water-borne infections",
    DiseaseGroup.VECTOR_BORNE: "Vector-borne infections",
    DiseaseGroup.VACCINE_PREVENTABLE: "Vaccine-preventable infections",
    DiseaseGroup.VIRAL_HEMORRHAGIC_FEVER: "Viral hemorrhagic fevers",
    DiseaseGroup.NEUROLOGIC_INVASIVE: "Neurologic / invasive infections",
    DiseaseGroup.BLOOD_BORNE_STI: "Blood-borne / sexually transmitted infections",
    DiseaseGroup.HEALTHCARE_ASSOCIATED_AMR: (
        "Healthcare-associated / antimicrobial-resistant infections"
    ),
    DiseaseGroup.OTHER_INFECTIOUS: "Other infectious diseases",
    DiseaseGroup.UNKNOWN: "Unknown / unclassified",
}


CANONICAL_DISEASE_GROUPS: dict[str, DiseaseGroup] = {
    "cholera": DiseaseGroup.ENTERIC_FOOD_WATERBORNE,
    "dengue": DiseaseGroup.VECTOR_BORNE,
    "measles": DiseaseGroup.VACCINE_PREVENTABLE,
    "mpox": DiseaseGroup.OTHER_INFECTIOUS,
    "ebola-virus-disease": DiseaseGroup.VIRAL_HEMORRHAGIC_FEVER,
    "marburg-virus-disease": DiseaseGroup.VIRAL_HEMORRHAGIC_FEVER,
    "yellow-fever": DiseaseGroup.VIRAL_HEMORRHAGIC_FEVER,
    "rabies": DiseaseGroup.NEUROLOGIC_INVASIVE,
    "west-nile-virus-disease": DiseaseGroup.VECTOR_BORNE,
    "chikungunya": DiseaseGroup.VECTOR_BORNE,
    "avian-influenza": DiseaseGroup.RESPIRATORY,
    "seasonal-influenza": DiseaseGroup.RESPIRATORY,
    "covid-19": DiseaseGroup.RESPIRATORY,
    "mers": DiseaseGroup.RESPIRATORY,
    "lassa-fever": DiseaseGroup.VIRAL_HEMORRHAGIC_FEVER,
    "rift-valley-fever": DiseaseGroup.VIRAL_HEMORRHAGIC_FEVER,
    "polio": DiseaseGroup.VACCINE_PREVENTABLE,
    "diphtheria": DiseaseGroup.VACCINE_PREVENTABLE,
    "pertussis": DiseaseGroup.VACCINE_PREVENTABLE,
    "meningococcal-disease": DiseaseGroup.VACCINE_PREVENTABLE,
    "anthrax": DiseaseGroup.OTHER_INFECTIOUS,
    "hantavirus-infection": DiseaseGroup.OTHER_INFECTIOUS,
    "leptospirosis": DiseaseGroup.OTHER_INFECTIOUS,
    "malaria": DiseaseGroup.VECTOR_BORNE,
    "zika-virus-disease": DiseaseGroup.VECTOR_BORNE,
    "typhoid-fever": DiseaseGroup.ENTERIC_FOOD_WATERBORNE,
    "salmonellosis": DiseaseGroup.ENTERIC_FOOD_WATERBORNE,
    "unknown-respiratory-illness": DiseaseGroup.UNKNOWN,
    "unknown-febrile-illness": DiseaseGroup.UNKNOWN,
    "unknown-disease": DiseaseGroup.UNKNOWN,
}


def disease_group_for(canonical_slug: str | None) -> DiseaseGroup:
    """Return reviewed group for canonical slug; never infer from text."""

    if canonical_slug is None:
        return DiseaseGroup.UNKNOWN
    return CANONICAL_DISEASE_GROUPS.get(canonical_slug, DiseaseGroup.UNKNOWN)


def disease_group_label(group: DiseaseGroup) -> str:
    return DISEASE_GROUP_LABELS[group]
