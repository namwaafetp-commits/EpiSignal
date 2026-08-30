import pytest
from episignal_backend.schedule.chains import CHAINS, DAILY_CHAIN, chain_for
from episignal_backend.schedule.documents import StageName


def test_triage_runs_after_dedupe_and_before_grouping() -> None:
    assert DAILY_CHAIN == (
        StageName.INGEST_WHO,
        StageName.INGEST_ECDC,
        StageName.DISCOVER,
        StageName.RETRIEVE,
        StageName.DEDUPE,
        StageName.TRIAGE,
        StageName.PREGROUP,
        StageName.EXTRACT,
        StageName.GEOCODE,
        StageName.MATCH,
    )


def test_retrieval_precedes_dedupe() -> None:
    # Dedupe compares bodies and is the only writer of `normalized`. A chain
    # that dedupes before retrieval strands every signal at `fetched`.
    assert DAILY_CHAIN.index(StageName.RETRIEVE) < DAILY_CHAIN.index(StageName.DEDUPE)


def test_grouping_precedes_extraction() -> None:
    assert DAILY_CHAIN.index(StageName.PREGROUP) < DAILY_CHAIN.index(StageName.EXTRACT)


def test_every_stage_appears_exactly_once() -> None:
    assert len(set(DAILY_CHAIN)) == len(DAILY_CHAIN)
    assert set(DAILY_CHAIN) == set(StageName)


def test_a_chain_is_looked_up_by_name() -> None:
    assert chain_for("daily") == DAILY_CHAIN
    assert set(CHAINS) == {"daily"}


def test_an_unknown_chain_is_refused_by_name() -> None:
    with pytest.raises(KeyError):
        chain_for("hourly")
