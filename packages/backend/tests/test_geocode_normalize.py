from episignal_backend.geocode.normalize import ascii_form, normalized_form


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
