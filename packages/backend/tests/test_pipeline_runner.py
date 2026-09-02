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


def test_failed_stage_outcomes_cross_the_repository_seam() -> None:
    from unittest.mock import MagicMock, patch
    from uuid import uuid4

    from episignal_backend.config import Settings
    from episignal_backend.db.types import PipelineRunStatus
    from episignal_backend.schedule.documents import ChainOutcome, StageName, StageOutcome

    fake_repo = MagicMock()
    fake_repo.try_lock.return_value = True
    fake_repo.last_window_end.return_value = None
    fake_repo.start_run.return_value = uuid4()
    fake_repo.backlog_depth.return_value = {}

    failed_outcome = StageOutcome(
        stage=StageName.EXTRACT,
        ok=False,
        counts={"attempted": 1},
        error="TimeoutError",
    )
    chain_outcome = ChainOutcome(outcomes=(failed_outcome,))

    with (
        patch("episignal_backend.pipeline_runner.session_scope"),
        patch(
            "episignal_backend.pipeline_runner.get_settings",
            return_value=Settings(
                database_url="postgresql://test:test@localhost/test", _env_file=None
            ),
        ),
        patch(
            "episignal_backend.pipeline_runner.SqlAlchemyPipelineRunRepository",
            return_value=fake_repo,
        ),
        patch("episignal_backend.pipeline_runner.run_chain", return_value=chain_outcome),
    ):
        from episignal_backend.pipeline_runner import main

        exit_code = main(["--only", "extract"])
        assert exit_code == 1

    fake_repo.finish_run.assert_called_once()
    _, kwargs = fake_repo.finish_run.call_args
    assert kwargs["status"] == PipelineRunStatus.FAILED
    assert kwargs["failed_stages"] == [failed_outcome]
