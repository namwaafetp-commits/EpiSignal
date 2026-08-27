from decimal import Decimal

from episignal_backend.seeds import load_diseases, load_sources


def test_disease_seed_natural_keys_are_unique() -> None:
    diseases = load_diseases()
    assert len(diseases) == 29
    assert len({item.slug for item in diseases}) == len(diseases)
    assert {item.canonical_name for item in diseases} >= {
        "Cholera",
        "Dengue",
        "Unknown disease",
    }


def test_source_seeds_are_official_and_unique() -> None:
    sources = load_sources()
    assert {item.name for item in sources} == {"WHO Disease Outbreak News", "ECDC"}
    assert all(item.is_official for item in sources)
    assert all(item.active is False for item in sources)


def test_query_rules_load_and_are_grouped() -> None:
    from episignal_backend.seeds import load_query_rules

    rules = load_query_rules()
    assert len(rules) >= 40
    groups = {rule.rule_group for rule in rules}
    assert groups == {
        "known_disease",
        "syndromic",
        "zoonotic",
        "public_health_abnormality",
    }


def test_query_rules_have_no_duplicate_identity() -> None:
    from episignal_backend.seeds import load_query_rules

    rules = load_query_rules()
    identities = [(rule.query, rule.language) for rule in rules]
    assert len(identities) == len(set(identities))


def test_no_query_rule_is_a_bare_generic_term() -> None:
    from episignal_backend.seeds import load_query_rules

    # A single generic query returns mostly noise and defeats grouping.
    banned = {"outbreak", "disease", "virus", "illness"}
    assert all(rule.query.strip().casefold() not in banned for rule in load_query_rules())


def test_filter_rules_load_and_are_all_negative() -> None:
    from episignal_backend.db.types import FilterRuleGroup
    from episignal_backend.seeds import load_filter_rules

    rules = load_filter_rules()

    assert len(rules) >= 10
    assert any(rule.rule_group is FilterRuleGroup.DOMAIN_BLOCKLIST for rule in rules)
    assert all(rule.pattern.strip() for rule in rules)


def test_every_seeded_title_pattern_compiles() -> None:
    import re

    from episignal_backend.db.types import FilterRuleGroup
    from episignal_backend.seeds import load_filter_rules

    for rule in load_filter_rules():
        if rule.rule_group is FilterRuleGroup.TITLE_EXCLUSION:
            re.compile(rule.pattern)


def test_no_seeded_rule_would_reject_a_real_outbreak_headline() -> None:
    from datetime import UTC, datetime

    from episignal_backend.ingestion.documents import DiscoveredArticle, FilterRule
    from episignal_backend.ingestion.filtering import compile_rules, evaluate
    from episignal_backend.seeds import load_filter_rules

    rules = compile_rules(
        tuple(
            FilterRule(rule_group=seed.rule_group, pattern=seed.pattern, label=seed.label)
            for seed in load_filter_rules()
        )
    )
    headlines = (
        "Measles outbreak spreads in Pennsylvania",
        "Cholera cases double in Juba after floods",
        "Health ministry confirms H5N1 in poultry workers",
        "Dos residentes no vacunados mueren de sarampion en Pensilvania",
        "Eighteen students hospitalised with unknown fever",
    )
    for headline in headlines:
        article = DiscoveredArticle(
            url="https://example.org/a",
            canonical_url="https://example.org/a",
            title=headline,
            domain="example.org",
            gdelt_seen_at=datetime(2026, 8, 27, 7, 45, tzinfo=UTC),
        )
        assert evaluate(article, rules) is None, headline


def test_the_seeded_roster_covers_all_three_tiers() -> None:
    from episignal_backend.seeds import load_ai_models

    models = load_ai_models()

    assert {model.tier for model in models} == {1, 2, 3}


def test_every_seeded_model_is_free() -> None:
    from episignal_backend.seeds import load_ai_models

    for model in load_ai_models():
        assert model.prompt_price_per_million == Decimal("0")
        assert model.completion_price_per_million == Decimal("0")


def test_no_two_seeded_models_share_an_identifier() -> None:
    from episignal_backend.seeds import load_ai_models

    identifiers = [model.model_id for model in load_ai_models()]

    assert len(identifiers) == len(set(identifiers))


def test_the_tiers_do_not_all_come_from_one_vendor() -> None:
    from episignal_backend.seeds import load_ai_models

    vendors = {model.model_id.split("/")[0] for model in load_ai_models()}

    assert len(vendors) > 1

