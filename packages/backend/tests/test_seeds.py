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
