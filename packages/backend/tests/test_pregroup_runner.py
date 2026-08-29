from datetime import UTC, datetime
from uuid import uuid4

import pytest
from episignal_backend.db.types import CredibilityTier
from episignal_backend.ingestion.pregroup import PreGroup, PreGroupSignal
from episignal_backend.ingestion.pregroup_store import SqlAlchemyPreGroupStore
from episignal_backend.pregroup_runner import PreGroupResult, parse_arguments


class FakeSession:
    def __init__(self, results: list | None = None) -> None:
        self._results = results or []
        self.added: list[object] = []
        self.executed: list[object] = []

    def execute(self, statement):
        self.executed.append(statement)
        return self._results.pop(0) if self._results else _Empty()

    def add(self, instance) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        return None

    def commit(self) -> None:
        return None


class _Empty:
    def scalars(self):
        return self

    def all(self):
        return []


def _signal(**overrides) -> PreGroupSignal:
    fields = {
        "signal_id": uuid4(),
        "rule_group": "known_disease",
        "country_code": "CD",
        "source_is_official": False,
        "credibility_tier": CredibilityTier.UNKNOWN,
        "first_seen_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return PreGroupSignal(**fields)


def test_write_groups_persists_one_row_per_group_with_roles() -> None:
    session = FakeSession()
    store = SqlAlchemyPreGroupStore(session)
    representative = _signal()
    deferred = _signal()
    group = PreGroup(
        rule_group="known_disease",
        country_code="CD",
        representative=representative,
        deferred=(deferred,),
    )

    written = store.write_groups([group], window_days=1, now=datetime.now(UTC))

    assert written == 1
    from episignal_backend.models import StoryGroup, StoryGroupMember

    group_rows = [item for item in session.added if isinstance(item, StoryGroup)]
    member_rows = [item for item in session.added if isinstance(item, StoryGroupMember)]
    assert len(group_rows) == 1
    assert group_rows[0].window_days == 1
    roles = {member.signal_id: member.role for member in member_rows}
    assert roles[representative.signal_id].value == "representative"
    assert roles[deferred.signal_id].value == "deferred"


def test_parse_arguments_reads_the_limit_and_ignores_the_separator() -> None:
    assert parse_arguments(["--", "--limit", "5"]).limit == 5
    assert parse_arguments([]).limit is None


def test_a_disabled_stage_reports_and_succeeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from episignal_backend import pregroup_runner

    class DisabledSettings:
        pregroup_enabled = False

    monkeypatch.setattr(pregroup_runner, "get_settings", lambda: DisabledSettings())

    from episignal_backend.pregroup_runner import main

    assert main([]) == 0
    assert "disabled" in capsys.readouterr().out


def test_an_enabled_stage_prints_its_counts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from episignal_backend import pregroup_runner

    class EnabledSettings:
        pregroup_enabled = True
        pregroup_batch_size = 10

    monkeypatch.setattr(pregroup_runner, "get_settings", lambda: EnabledSettings())
    monkeypatch.setattr(
        pregroup_runner,
        "_run",
        lambda arguments: PreGroupResult(examined=10, groups=4, deferred=6, resolved=2, expired=1),
    )

    assert pregroup_runner.main([]) == 0
    out = capsys.readouterr().out
    assert "examined=10" in out and "groups=4" in out and "deferred=6" in out
