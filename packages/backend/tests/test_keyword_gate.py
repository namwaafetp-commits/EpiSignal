from uuid import uuid4

from episignal_backend.db.types import FilterRuleGroup
from episignal_backend.ingestion.documents import FilterRule
from episignal_backend.ingestion.keyword_gate import classify_title

OUTBREAK = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.TITLE_INCLUSION,
    pattern="outbreak",
    label="Context: outbreak",
)
MEASLES = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.TITLE_INCLUSION,
    pattern="measles",
    label="Disease: Measles",
)
EXCLUSION = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.TITLE_EXCLUSION,
    pattern=r"\bfever pitch\b",
    label="Fever pitch metaphor",
)


def test_a_disease_name_passes_the_gate() -> None:
    decision = classify_title("Measles spreads in Hanoi", (MEASLES, OUTBREAK))

    assert decision.passed is True
    assert decision.rule is MEASLES


def test_a_context_term_passes_the_gate() -> None:
    decision = classify_title("Health officials confirm outbreak", (MEASLES, OUTBREAK))

    assert decision.passed is True
    assert decision.rule is OUTBREAK


def test_a_clean_headline_is_filtered() -> None:
    decision = classify_title("City council approves new stadium", (MEASLES, OUTBREAK))

    assert decision.passed is False
    assert decision.rule is None


def test_matching_ignores_case_and_collapsed_whitespace() -> None:
    decision = classify_title("MEASLES\n  outbreak  declared", (MEASLES,))

    assert decision.passed is True


def test_an_empty_rule_set_passes_everything() -> None:
    # The gate can never be the reason a run stores nothing.
    decision = classify_title("City council approves new stadium", ())

    assert decision.passed is True
    assert decision.rule is None


def test_only_inclusion_rules_are_consulted() -> None:
    # Exclusion is discovery's job and runs before a signal exists at all.
    decision = classify_title("Fever pitch at the derby", (EXCLUSION,))

    assert decision.passed is True
    assert decision.rule is None


def test_a_blank_title_is_filtered() -> None:
    decision = classify_title("   ", (MEASLES,))

    assert decision.passed is False
