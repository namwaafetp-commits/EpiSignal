from collections.abc import Mapping

from episignal_backend.schedule.documents import StageName
from episignal_backend.schedule.run import run_chain


def _record(calls: list[StageName], stage: StageName, counts: dict[str, int]):
    def runner() -> Mapping[str, int]:
        calls.append(stage)
        return counts

    return runner


def _raises(calls: list[StageName], stage: StageName, error: Exception):
    def runner() -> Mapping[str, int]:
        calls.append(stage)
        raise error

    return runner


def test_stages_run_in_the_order_the_chain_gives() -> None:
    calls: list[StageName] = []
    chain = (StageName.DEDUPE, StageName.EXTRACT, StageName.GEOCODE)
    runners = {stage: _record(calls, stage, {"examined": 1}) for stage in chain}

    run_chain(chain, runners)

    assert calls == [StageName.DEDUPE, StageName.EXTRACT, StageName.GEOCODE]


def test_a_failing_stage_does_not_stop_the_ones_after_it() -> None:
    calls: list[StageName] = []
    chain = (StageName.EXTRACT, StageName.GEOCODE, StageName.MATCH)
    runners = {
        StageName.EXTRACT: _raises(calls, StageName.EXTRACT, TimeoutError("upstream")),
        StageName.GEOCODE: _record(calls, StageName.GEOCODE, {"located": 4}),
        StageName.MATCH: _record(calls, StageName.MATCH, {"created": 1}),
    }

    outcome = run_chain(chain, runners)

    assert calls == [StageName.EXTRACT, StageName.GEOCODE, StageName.MATCH]
    assert outcome.ok is False
    assert outcome.failed_stages == (StageName.EXTRACT,)


def test_a_failure_records_the_exception_type_and_never_its_message() -> None:
    chain = (StageName.MATCH,)
    secret = "postgresql://user:hunter2@host/db is unreachable"
    runners = {StageName.MATCH: _raises([], StageName.MATCH, OSError(secret))}

    outcome = run_chain(chain, runners)

    assert outcome.outcomes[0].error == "OSError"
    assert "hunter2" not in str(outcome.outcomes[0])


def test_counts_are_kept_per_stage() -> None:
    chain = (StageName.GEOCODE,)
    runners = {StageName.GEOCODE: _record([], StageName.GEOCODE, {"located": 7})}

    outcome = run_chain(chain, runners)

    assert outcome.outcomes[0].counts == {"located": 7}
    assert outcome.ok is True


def test_stage_duration_is_diagnostic_and_does_not_change_success_behavior() -> None:
    chain = (StageName.DEDUPE,)
    outcome = run_chain(chain, {StageName.DEDUPE: _record([], StageName.DEDUPE, {"examined": 1})})

    assert outcome.ok is True
    assert outcome.outcomes[0].duration_sec is not None
    assert outcome.outcomes[0].duration_sec >= 0


def test_a_stage_with_no_runner_is_a_failure_not_a_crash() -> None:
    outcome = run_chain((StageName.MATCH,), {})

    assert outcome.ok is False
    assert outcome.outcomes[0].error == "KeyError"
