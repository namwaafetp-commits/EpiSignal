import pytest
from episignal_backend.schedule.chains import CHAINS, DAILY_CHAIN, chain_for
from episignal_backend.schedule.documents import StageName


def test_daily_chain_contains_only_the_lean_mvp_runtime_stages() -> None:
    assert DAILY_CHAIN == (
        StageName.INGEST_WHO,
        StageName.DISCOVER,
        StageName.CLASSIFY,
        StageName.RETRIEVE,
        StageName.DEDUPE,
        StageName.EXTRACT,
        StageName.MATCH,
        StageName.SUMMARIZE,
    )


def test_summarization_runs_after_matching() -> None:
    assert DAILY_CHAIN.index(StageName.SUMMARIZE) > DAILY_CHAIN.index(StageName.MATCH)


def test_retrieval_precedes_dedupe() -> None:
    # Dedupe compares bodies and is the only writer of `normalized`. A chain
    # that dedupes before retrieval strands every signal at `fetched`.
    assert DAILY_CHAIN.index(StageName.RETRIEVE) < DAILY_CHAIN.index(StageName.DEDUPE)


def test_the_runtime_does_not_schedule_retired_stages() -> None:
    assert not set(DAILY_CHAIN) & {
        StageName.INGEST_ECDC,
        StageName.PREGROUP,
        StageName.GEOCODE,
        StageName.EMBED,
    }


def test_every_stage_appears_exactly_once() -> None:
    assert len(set(DAILY_CHAIN)) == len(DAILY_CHAIN)
    assert set(DAILY_CHAIN) == {
        StageName.INGEST_WHO,
        StageName.DISCOVER,
        StageName.CLASSIFY,
        StageName.RETRIEVE,
        StageName.DEDUPE,
        StageName.EXTRACT,
        StageName.MATCH,
        StageName.SUMMARIZE,
    }


def test_a_chain_is_looked_up_by_name() -> None:
    assert chain_for("daily") == DAILY_CHAIN
    assert set(CHAINS) == {"daily"}


def test_an_unknown_chain_is_refused_by_name() -> None:
    with pytest.raises(KeyError):
        chain_for("hourly")
