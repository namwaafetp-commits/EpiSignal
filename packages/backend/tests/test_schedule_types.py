from episignal_backend.db.types import (
    PipelineChain,
    PipelineRunStatus,
    PipelineTrigger,
    vocabulary,
)


def test_the_vocabularies_store_their_lowercase_values() -> None:
    assert PipelineChain.DAILY == "daily"
    assert PipelineTrigger.SCHEDULED == "scheduled"
    assert PipelineRunStatus.RUNNING == "running"


def test_a_run_is_running_succeeded_or_failed() -> None:
    assert {status.value for status in PipelineRunStatus} == {
        "running",
        "succeeded",
        "failed",
    }


def test_a_scheduled_run_is_distinguishable_from_a_manual_one() -> None:
    # The MVP question is whether Task Scheduler actually fired, which a run
    # invoked by hand would otherwise disguise.
    assert {trigger.value for trigger in PipelineTrigger} == {"scheduled", "manual"}


def test_the_vocabularies_are_stored_as_values_not_member_names() -> None:
    column_type = vocabulary(PipelineRunStatus, "pipeline_run_status")

    assert sorted(column_type.enums) == ["failed", "running", "succeeded"]
