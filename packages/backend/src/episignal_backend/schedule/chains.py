"""The order the stages run in.

One chain exists. The order is a decision, not an accident: WHO and ECDC are
ingested first so an official document that corroborates a story is in the
database before that story's media coverage is matched to an event.
"""

from episignal_backend.schedule.documents import StageName

DAILY_CHAIN: tuple[StageName, ...] = (
    StageName.INGEST_WHO,
    StageName.INGEST_ECDC,
    StageName.DISCOVER,
    StageName.RETRIEVE,
    StageName.DEDUPE,
    StageName.TRIAGE,
    StageName.EMBED,
    StageName.PREGROUP,
    StageName.EXTRACT,
    StageName.GEOCODE,
    StageName.MATCH,
)

CHAINS: dict[str, tuple[StageName, ...]] = {"daily": DAILY_CHAIN}


def chain_for(name: str) -> tuple[StageName, ...]:
    return CHAINS[name]
