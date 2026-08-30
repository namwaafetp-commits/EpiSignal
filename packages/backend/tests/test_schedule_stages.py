from datetime import UTC, datetime

from episignal_backend.schedule.chains import DAILY_CHAIN
from episignal_backend.schedule.documents import DiscoveryWindow, StageName
from episignal_backend.schedule.stages import build_stage_runners

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def test_every_stage_in_the_daily_chain_has_a_runner() -> None:
    runners = build_stage_runners(window=DiscoveryWindow(start=NOW, end=NOW))

    for stage in DAILY_CHAIN:
        assert stage in runners


def test_no_runner_is_called_while_the_mapping_is_being_built() -> None:
    # Building the mapping must not open a session, read settings, or construct
    # an OpenRouter client, or importing the module would need a database.
    runners = build_stage_runners(window=DiscoveryWindow(start=NOW, end=NOW))

    assert callable(runners[StageName.EXTRACT])


def test_the_mapping_covers_exactly_the_stage_names() -> None:
    runners = build_stage_runners(window=DiscoveryWindow(start=NOW, end=NOW))

    assert set(runners) == set(StageName)
