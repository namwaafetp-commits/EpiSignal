from datetime import UTC, datetime
from uuid import uuid4

from episignal_backend.db.types import FilterRuleGroup
from episignal_backend.ingestion.documents import DiscoveredArticle, FilterRule
from episignal_backend.ingestion.filtering import compile_rules, evaluate

SEEN = datetime(2026, 8, 27, 7, 45, tzinfo=UTC)

VIOLENCE = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.TITLE_EXCLUSION,
    pattern=r"\boutbreak of (violence|unrest)\b",
    label="Outbreak of violence",
)
WIRE = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.DOMAIN_BLOCKLIST,
    pattern="prnewswire.com",
    label="Press release wire",
)
BROKEN = FilterRule(
    id=uuid4(),
    rule_group=FilterRuleGroup.TITLE_EXCLUSION,
    pattern=r"([unclosed",
    label="Broken rule",
)


def article(title: str, domain: str = "example.vn") -> DiscoveredArticle:
    return DiscoveredArticle(
        url=f"https://{domain}/story",
        canonical_url=f"https://{domain}/story",
        title=title,
        domain=domain,
        gdelt_seen_at=SEEN,
    )


def test_a_metaphorical_title_is_rejected() -> None:
    rules = compile_rules((VIOLENCE,))

    assert evaluate(article("Outbreak of violence in the capital"), rules) is VIOLENCE


def test_matching_ignores_case() -> None:
    rules = compile_rules((VIOLENCE,))

    assert evaluate(article("OUTBREAK OF UNREST grips the city"), rules) is VIOLENCE


def test_a_real_outbreak_report_is_kept() -> None:
    rules = compile_rules((VIOLENCE, WIRE))

    assert evaluate(article("Measles outbreak spreads in Pennsylvania"), rules) is None


def test_an_article_with_no_rules_is_kept() -> None:
    rules = compile_rules(())

    assert evaluate(article("Anything at all"), rules) is None


def test_a_blocklisted_domain_is_rejected() -> None:
    rules = compile_rules((WIRE,))

    assert evaluate(article("Vaccine maker reports results", "prnewswire.com"), rules) is WIRE


def test_a_subdomain_of_a_blocklisted_domain_is_rejected() -> None:
    rules = compile_rules((WIRE,))

    assert evaluate(article("Vaccine maker reports", "www.prnewswire.com"), rules) is WIRE


def test_a_lookalike_domain_is_kept() -> None:
    rules = compile_rules((WIRE,))

    assert evaluate(article("Cholera cases rise", "notprnewswire.com"), rules) is None


def test_an_invalid_pattern_is_skipped_without_failing_the_run() -> None:
    rules = compile_rules((BROKEN, VIOLENCE))

    assert rules.invalid == 1
    assert evaluate(article("Outbreak of violence in the capital"), rules) is VIOLENCE
    assert evaluate(article("Dengue cases double"), rules) is None
