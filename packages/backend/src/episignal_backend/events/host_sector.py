"""Host-sector rules shared by signal and event read paths."""

from collections.abc import Iterable

from episignal_backend.db.types import HostSector


def normalize_host_sector(value: HostSector | str | None) -> HostSector:
    if value is None:
        return HostSector.UNKNOWN
    try:
        return HostSector(value)
    except ValueError:
        return HostSector.UNKNOWN


def derive_event_host_sector(values: Iterable[HostSector | str | None]) -> HostSector:
    sectors = {normalize_host_sector(value) for value in values}
    if HostSector.BOTH in sectors:
        return HostSector.BOTH
    if HostSector.HUMAN in sectors and HostSector.ANIMAL in sectors:
        return HostSector.BOTH
    if HostSector.HUMAN in sectors:
        return HostSector.HUMAN
    if HostSector.ANIMAL in sectors:
        return HostSector.ANIMAL
    return HostSector.UNKNOWN
