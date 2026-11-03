import pytest
from episignal_backend.db.types import HostSector
from episignal_backend.events.host_sector import derive_event_host_sector, normalize_host_sector


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ((HostSector.HUMAN,), HostSector.HUMAN),
        ((HostSector.ANIMAL,), HostSector.ANIMAL),
        ((HostSector.HUMAN, HostSector.ANIMAL), HostSector.BOTH),
        ((HostSector.BOTH,), HostSector.BOTH),
        ((HostSector.HUMAN, HostSector.UNKNOWN), HostSector.HUMAN),
        ((HostSector.ANIMAL, HostSector.UNKNOWN), HostSector.ANIMAL),
        ((HostSector.UNKNOWN,), HostSector.UNKNOWN),
        ((), HostSector.UNKNOWN),
    ],
)
def test_event_host_sector_uses_explicit_precedence(values, expected) -> None:
    assert derive_event_host_sector(values) is expected


def test_missing_historical_value_is_unknown() -> None:
    assert normalize_host_sector(None) is HostSector.UNKNOWN
    assert normalize_host_sector("not-a-sector") is HostSector.UNKNOWN
