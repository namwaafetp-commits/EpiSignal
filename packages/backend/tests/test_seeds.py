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
