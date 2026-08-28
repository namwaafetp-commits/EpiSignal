import pytest
from episignal_backend.schedule.chains import CHAINS, DAILY_CHAIN, chain_for
from episignal_backend.schedule.documents import StageName


def test_official_sources_are_ingested_before_media_is_matched() -> None:
    assert DAILY_CHAIN == (
        StageName.INGEST_WHO,
        StageName.INGEST_ECDC,
        StageName.DISCOVER,
        StageName.DEDUPE,
        StageName.EXTRACT,
        StageName.GEOCODE,
        StageName.MATCH,
    )


def test_every_stage_appears_exactly_once() -> None:
    assert len(set(DAILY_CHAIN)) == len(DAILY_CHAIN)
    assert set(DAILY_CHAIN) == set(StageName)


def test_a_chain_is_looked_up_by_name() -> None:
    assert chain_for("daily") == DAILY_CHAIN
    assert set(CHAINS) == {"daily"}


def test_an_unknown_chain_is_refused_by_name() -> None:
    with pytest.raises(KeyError):
        chain_for("hourly")
