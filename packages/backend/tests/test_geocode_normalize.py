from episignal_backend.geocode.normalize import (
    ascii_form,
    normalized_form,
    resolve_country,
)

ALIASES = {
    "democratic republic of the congo": "CD",
    "dr congo": "CD",
    "congo dem rep": "CD",
    "niger": "NE",
    "nigeria": "NG",
}


def test_the_normalized_form_casefolds() -> None:
    assert normalized_form("BIKORO") == "bikoro"


def test_the_normalized_form_collapses_whitespace() -> None:
    assert normalized_form("  Port   Harcourt \n") == "port harcourt"


def test_the_normalized_form_turns_punctuation_into_a_separator() -> None:
    assert normalized_form("Saint-Louis") == "saint louis"
    assert normalized_form("N'Djamena") == "n djamena"


def test_the_normalized_form_keeps_diacritics() -> None:
    assert normalized_form("Équateur") == "équateur"


def test_the_ascii_form_folds_diacritics() -> None:
    assert ascii_form("Équateur") == "equateur"
    assert ascii_form("Kraków") == "krakow"
    assert ascii_form("São Paulo") == "sao paulo"


def test_the_ascii_form_applies_every_normalization_too() -> None:
    assert ascii_form("  SAINT-LOUIS  ") == "saint louis"


def test_both_forms_return_empty_for_a_name_that_is_only_punctuation() -> None:
    assert normalized_form("---") == ""
    assert ascii_form("---") == ""


def test_it_resolves_an_exact_alias() -> None:
    assert resolve_country("DR Congo", ALIASES) == "CD"


def test_it_resolves_through_the_normalized_form() -> None:
    assert resolve_country("  Congo, Dem. Rep. ", ALIASES) == "CD"


def test_it_returns_none_when_no_alias_matches() -> None:
    assert resolve_country("Ruritania", ALIASES) is None


def test_it_returns_none_for_a_missing_country() -> None:
    assert resolve_country(None, ALIASES) is None


def test_it_never_matches_a_near_miss() -> None:
    # Niger and Nigeria are the canonical example of the error this project
    # treats as worst. Exact matching is the reason it cannot happen.
    assert resolve_country("Niger", ALIASES) == "NE"
    assert resolve_country("Nigeria", ALIASES) == "NG"
    assert resolve_country("Nigerien", ALIASES) is None
