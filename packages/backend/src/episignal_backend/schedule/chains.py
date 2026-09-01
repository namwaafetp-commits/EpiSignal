"""Lean MVP runtime stage order."""

from episignal_backend.schedule.documents import StageName

DAILY_CHAIN: tuple[StageName, ...] = (
    StageName.INGEST_WHO,
    StageName.DISCOVER,
    StageName.DEDUPE,
    StageName.CLASSIFY,
    StageName.RETRIEVE,
    StageName.EXTRACT,
    StageName.MATCH,
    StageName.SUMMARIZE,
)

CHAINS: dict[str, tuple[StageName, ...]] = {"daily": DAILY_CHAIN}


def chain_for(name: str) -> tuple[StageName, ...]:
    return CHAINS[name]
