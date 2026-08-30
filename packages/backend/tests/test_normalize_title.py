from episignal_backend.ingestion.normalize_title import normalize_title


def test_case_and_whitespace_are_collapsed() -> None:
    assert normalize_title("  Dengue   Outbreak\nIn Chiang Mai ") == "dengue outbreak in chiang mai"


def test_a_publisher_suffix_is_dropped() -> None:
    assert (
        normalize_title("Dengue outbreak in Chiang Mai - Bangkok Post")
        == "dengue outbreak in chiang mai"
    )
    assert (
        normalize_title("Dengue outbreak in Chiang Mai | Reuters")
        == "dengue outbreak in chiang mai"
    )


def test_a_hyphenated_phrase_is_not_mistaken_for_a_suffix() -> None:
    # Only a suffix after the LAST separator, and only when what follows is
    # short enough to be a masthead rather than part of the headline.
    assert (
        normalize_title("Mother-to-child transmission confirmed")
        == "mother-to-child transmission confirmed"
    )


def test_punctuation_and_unicode_are_folded() -> None:
    assert normalize_title("Dengue “outbreak” in Chiang Mai!") == "dengue outbreak in chiang mai"
    assert normalize_title("DENGUE OUTBREAK") == "dengue outbreak"


def test_two_genuinely_different_headlines_do_not_collapse() -> None:
    first = normalize_title("Dengue outbreak in Chiang Mai")
    second = normalize_title("Dengue outbreak in Phuket")

    assert first != second


def test_a_blank_title_normalizes_to_empty() -> None:
    assert normalize_title("   ") == ""
