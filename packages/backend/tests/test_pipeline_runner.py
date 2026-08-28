from episignal_backend.pipeline_runner import parse_arguments
from episignal_backend.schedule.documents import StageName


def test_a_bare_invocation_runs_the_whole_chain() -> None:
    arguments = parse_arguments([])

    assert arguments.only is None
    assert arguments.trigger == "manual"


def test_pnpm_double_dash_is_not_mistaken_for_an_argument() -> None:
    arguments = parse_arguments(["--", "--only", "match"])

    assert arguments.only == StageName.MATCH


def test_a_scheduled_run_says_so() -> None:
    # This is how "did Task Scheduler actually fire" is answerable later.
    assert parse_arguments(["--trigger", "scheduled"]).trigger == "scheduled"


def test_only_accepts_a_real_stage_name() -> None:
    import pytest

    with pytest.raises(SystemExit):
        parse_arguments(["--only", "publish"])
