from episignal_backend.db.types import Precision


def test_precision_is_ordered_from_specific_to_absent() -> None:
    assert [member.value for member in Precision] == [
        "place",
        "admin2",
        "admin1",
        "country",
        "unresolved",
    ]


def test_precision_stores_its_values_not_its_member_names() -> None:
    assert Precision.ADMIN1 == "admin1"
    assert str(Precision.UNRESOLVED) == "unresolved"
