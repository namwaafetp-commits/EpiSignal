import pytest
from episignal_backend.ingestion.gdelt.locale import country_code, language_code


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("English", "en"),
        ("Spanish", "es"),
        ("Vietnamese", "vi"),
        ("Thai", "th"),
        ("  spanish  ", "es"),
        ("SPANISH", "es"),
    ],
)
def test_language_code_maps_known_names(name: str, expected: str) -> None:
    assert language_code(name) == expected


@pytest.mark.parametrize("name", ["", "   ", "Klingon", "Not A Language"])
def test_language_code_returns_none_for_unmapped_names(name: str) -> None:
    assert language_code(name) is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("United States", "US"),
        ("Vietnam", "VN"),
        ("Viet Nam", "VN"),
        ("Thailand", "TH"),
        ("  united states  ", "US"),
    ],
)
def test_country_code_maps_known_names(name: str, expected: str) -> None:
    assert country_code(name) == expected


@pytest.mark.parametrize("name", ["", "   ", "Atlantis"])
def test_country_code_returns_none_for_unmapped_names(name: str) -> None:
    assert country_code(name) is None


def test_every_language_code_fits_the_column() -> None:
    from episignal_backend.ingestion.gdelt.locale import LANGUAGE_CODES

    assert all(len(code) <= 8 for code in LANGUAGE_CODES.values())


def test_every_country_code_fits_the_column() -> None:
    from episignal_backend.ingestion.gdelt.locale import COUNTRY_CODES

    assert all(len(code) == 2 for code in COUNTRY_CODES.values())
