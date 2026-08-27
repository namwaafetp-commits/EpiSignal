import pytest
from episignal_backend.db.types import Precision
from episignal_backend.geocode.documents import MatchForm
from episignal_backend.geocode.resolve import confidence_for


def test_an_exact_place_match_is_the_most_confident_answer() -> None:
    assert confidence_for(Precision.PLACE, MatchForm.EXACT) == 0.95


def test_a_folded_place_match_scores_below_an_exact_one() -> None:
    assert confidence_for(Precision.PLACE, MatchForm.ASCII) == 0.85


def test_an_alternate_name_match_scores_below_a_folded_one() -> None:
    assert confidence_for(Precision.PLACE, MatchForm.ALTERNATE) == 0.75


def test_coarser_precision_scores_lower_regardless_of_form() -> None:
    assert confidence_for(Precision.ADMIN2, MatchForm.EXACT) == 0.70
    assert confidence_for(Precision.ADMIN1, None) == 0.55
    assert confidence_for(Precision.COUNTRY, None) == 0.30


def test_an_unresolved_location_has_no_confidence_rather_than_zero() -> None:
    assert confidence_for(Precision.UNRESOLVED, None) is None


def test_a_place_precision_without_a_form_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        confidence_for(Precision.PLACE, None)
