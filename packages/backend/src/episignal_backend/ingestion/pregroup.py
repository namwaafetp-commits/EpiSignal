"""The pre-group stage: one representative per story, decided before any AI call.

Groups `normalized` signals by the only disease and place facts that exist
before extraction — the query rule's group (the query library is
disease-keyed), the publisher's country, and a day window. One representative
per group proceeds to classification and extraction; the others defer.

Two boundaries from the design hold here: a deferred signal is never evidence
(its group membership is routing, nothing else), and a signal missing its rule
or its country forms its own group rather than being dropped, because absence
of a grouping fact is not absence of the signal.

This module imports neither SQLAlchemy nor httpx.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from episignal_backend.db.types import CredibilityTier

MAX_WINDOW_DAYS = 2

_CREDIBILITY_RANK: dict[CredibilityTier, int] = {
    CredibilityTier.OFFICIAL: 3,
    CredibilityTier.HIGH: 2,
    CredibilityTier.MEDIUM: 1,
    CredibilityTier.UNKNOWN: 0,
}


class GroupRole(StrEnum):
    """What a member owes its group. `representative` proceeds; `deferred` waits."""

    REPRESENTATIVE = "representative"
    DEFERRED = "deferred"


class PreGroupSignal(BaseModel):
    """The grouping facts of one normalized signal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: UUID
    rule_group: str | None = None
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    source_is_official: bool = False
    credibility_tier: CredibilityTier = CredibilityTier.UNKNOWN
    first_seen_at: datetime


@dataclass(frozen=True)
class PreGroup:
    """One group: a key, a representative, and the members waiting on it."""

    rule_group: str | None
    country_code: str | None
    representative: PreGroupSignal
    deferred: tuple[PreGroupSignal, ...]

    @property
    def key(self) -> tuple[str | None, str | None]:
        return (self.rule_group, self.country_code)


def representative_rank(signal: PreGroupSignal) -> tuple[int, int, datetime, str]:
    """Official standing first, then credibility, then the earliest sighting.

    The earliest-sighted rule dominates in practice because GDELT publishers
    start as unknown, exactly as the dedupe gate documents; the standing ranks
    exist so the preference becomes true as source standing accumulates,
    without another change here. The UUID keeps the order total.
    """
    return (
        0 if signal.source_is_official else 1,
        -_CREDIBILITY_RANK.get(signal.credibility_tier, 0),
        signal.first_seen_at,
        str(signal.signal_id),
    )


def group_signals(signals: list[PreGroupSignal], *, window_days: int = 1) -> tuple[PreGroup, ...]:
    """Group by rule group, country, and day window; one representative each.

    `window_days` is the distance in days two sightings may span and still be
    one story; the design caps it at two, and the configuration enforces that
    before it reaches here.
    """
    if not 1 <= window_days <= MAX_WINDOW_DAYS:
        raise ValueError(f"window_days must be between 1 and {MAX_WINDOW_DAYS}")

    grouped: dict[tuple[str | None, str | None], list[PreGroupSignal]] = {}
    for signal in signals:
        grouped.setdefault(_key_of(signal), []).append(signal)

    groups: list[PreGroup] = []
    for (rule_group, country_code), members in grouped.items():
        for chain in _chains(members, window_days):
            ordered = sorted(chain, key=representative_rank)
            groups.append(
                PreGroup(
                    rule_group=rule_group,
                    country_code=country_code,
                    representative=ordered[0],
                    deferred=tuple(ordered[1:]),
                )
            )
    return tuple(groups)


def _key_of(signal: PreGroupSignal) -> tuple[str | None, str | None]:
    return (signal.rule_group, signal.country_code)


def _chains(members: list[PreGroupSignal], window_days: int) -> list[list[PreGroupSignal]]:
    """Split one key's members into time chains.

    Sorted by first sighting, a member joins the open chain while it is within
    the window of the chain's latest member; a gap opens a new chain, so one
    country's week of coverage becomes several stories rather than one
    unbounded group.
    """
    ordered = sorted(members, key=lambda signal: (signal.first_seen_at, str(signal.signal_id)))
    chains: list[list[PreGroupSignal]] = []
    for signal in ordered:
        if chains:
            latest = chains[-1][-1]
            if (signal.first_seen_at - latest.first_seen_at).days <= window_days:
                chains[-1].append(signal)
                continue
        chains.append([signal])
    return chains
