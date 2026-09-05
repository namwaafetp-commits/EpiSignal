"""Acceptance tests for the in-memory cohort boundary."""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from episignal_backend.ai.classify import run_classification
from episignal_backend.ai.documents import ModelSpec
from episignal_backend.ai.extract import run_extraction
from episignal_backend.ai.ladder import Guards
from episignal_backend.db.types import AiProvider, AiPurpose
from episignal_backend.events.assemble import run_event_assembly
from episignal_backend.ingestion.dedupe import run_dedupe
from episignal_backend.ingestion.retrieval import run_retrieval
from episignal_backend.schedule import stages
from episignal_backend.schedule.chains import DAILY_CHAIN
from episignal_backend.schedule.documents import DiscoveryWindow, PipelineCohort, StageName
from episignal_backend.schedule.run import run_chain

NOW = datetime(2026, 9, 3, 8, 0, tzinfo=UTC)
COHORT = tuple(UUID(f"00000000-0000-4000-8000-00000000000{i}") for i in (1, 2, 3))
HISTORY = tuple(UUID(f"00000000-0000-4000-8000-00000000000{i}") for i in (4, 5, 6))


class EmptyDedupeRepository:
    def __init__(self) -> None:
        self.requested: Sequence[UUID] | None = None

    def pending(self, *, limit: int, signal_ids: Sequence[UUID] | None = None):
        self.requested = signal_ids
        return ()

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class EmptyRetrievalRepository:
    def __init__(self) -> None:
        self.requested: Sequence[UUID] | None = None

    def gated_awaiting_retrieval(self, *, max_attempts: int, limit: int, signal_ids=None):
        self.requested = signal_ids
        return ()


class EmptyAiRepository:
    def __init__(self) -> None:
        self.classification_ids: Sequence[UUID] | None = None
        self.extraction_ids: Sequence[UUID] | None = None

    def models(self):
        return (
            ModelSpec(
                id=uuid4(),
                tier=1,
                model_id="deepseek/deepseek-v4-flash-0731",
                label="test",
                provider=AiProvider.OPENROUTER,
                purpose=AiPurpose.CLASSIFICATION,
                prompt_price_per_million=Decimal("0"),
                completion_price_per_million=Decimal("0"),
            ),
            ModelSpec(
                id=uuid4(),
                tier=1,
                model_id="google/gemini-3.1-flash-lite",
                label="test extract",
                provider=AiProvider.GEMINI,
                purpose=AiPurpose.EXTRACTION,
                prompt_price_per_million=Decimal("0"),
                completion_price_per_million=Decimal("0"),
            ),
        )

    def awaiting_classification(self, *, limit: int, signal_ids=None):
        self.classification_ids = signal_ids
        return ()

    def awaiting_extraction(self, *, limit: int, signal_ids=None):
        self.extraction_ids = signal_ids
        return ()


class EmptyEventRepository:
    def __init__(self) -> None:
        self.match_ids: Sequence[UUID] | None = None
        self.summary_ids: Sequence[UUID] | None = None

    def signals_to_match(self, limit: int, *, stale: bool = False, signal_ids=None):
        self.match_ids = signal_ids
        return ()

    def events_awaiting_summary(self, *, limit: int, max_age_hours: int, event_ids=None):
        self.summary_ids = event_ids
        return ()

    def commit(self) -> None:
        pass


def test_runner_propagates_one_cohort_through_every_downstream_stage(monkeypatch) -> None:
    seen: dict[StageName, tuple[UUID, ...]] = {}
    touched = (uuid4(),)

    def discover(window, cohort):
        cohort.signal_ids = COHORT
        return {"new_signals": 3}

    def downstream(stage):
        def run(cohort):
            seen[stage] = cohort.signal_ids
            if stage is StageName.MATCH:
                cohort.touched_event_ids = touched
            return {}

        return run

    monkeypatch.setattr(stages, "_ingest", lambda connector, window, cohort: {})
    monkeypatch.setattr(stages, "_discover", discover)
    for stage in (
        StageName.DEDUPE,
        StageName.CLASSIFY,
        StageName.RETRIEVE,
        StageName.EXTRACT,
        StageName.MATCH,
        StageName.SUMMARIZE,
    ):
        monkeypatch.setattr(stages, f"_{stage.value}", downstream(stage))

    outcome = run_chain(
        DAILY_CHAIN,
        stages.build_stage_runners(
            window=DiscoveryWindow(start=NOW, end=NOW), cohort=PipelineCohort()
        ),
    )

    assert outcome.ok
    assert all(ids == COHORT for ids in seen.values())


def test_empty_cohort_performs_no_downstream_work(monkeypatch) -> None:
    calls: list[tuple[StageName, tuple[UUID, ...]]] = []
    monkeypatch.setattr(stages, "_ingest", lambda connector, window, cohort: {})
    monkeypatch.setattr(stages, "_discover", lambda window, cohort: {})
    for stage in (
        StageName.DEDUPE,
        StageName.CLASSIFY,
        StageName.RETRIEVE,
        StageName.EXTRACT,
        StageName.MATCH,
        StageName.SUMMARIZE,
    ):
        monkeypatch.setattr(
            stages,
            f"_{stage.value}",
            lambda cohort, stage=stage: calls.append((stage, cohort.signal_ids)) or {},
        )

    run_chain(
        DAILY_CHAIN,
        stages.build_stage_runners(
            window=DiscoveryWindow(start=NOW, end=NOW), cohort=PipelineCohort()
        ),
    )

    assert calls == [
        (stage, ())
        for stage in (
            StageName.DEDUPE,
            StageName.CLASSIFY,
            StageName.RETRIEVE,
            StageName.EXTRACT,
            StageName.MATCH,
            StageName.SUMMARIZE,
        )
    ]


def test_dedupe_selection_is_cohort_scoped() -> None:
    repository = EmptyDedupeRepository()
    run_dedupe(repository, signal_ids=COHORT)
    assert tuple(repository.requested or ()) == COHORT


def test_classification_selection_is_cohort_scoped() -> None:
    repository = EmptyAiRepository()
    run_classification(
        repository,
        object(),
        guards=Guards(max_requests=1, max_cost_usd=Decimal("1")),
        signal_ids=COHORT,
    )
    assert tuple(repository.classification_ids or ()) == COHORT


def test_retrieval_selection_is_cohort_scoped() -> None:
    repository = EmptyRetrievalRepository()
    run_retrieval(repository, object(), signal_ids=COHORT)
    assert tuple(repository.requested or ()) == COHORT


def test_extraction_selection_is_cohort_scoped() -> None:
    repository = EmptyAiRepository()
    run_extraction(
        repository,
        object(),
        guards=Guards(max_requests=1, max_cost_usd=Decimal("1")),
        signal_ids=COHORT,
    )
    assert tuple(repository.extraction_ids or ()) == COHORT


def test_grouping_reads_candidates_but_matches_only_cohort() -> None:
    repository = EmptyEventRepository()
    run_event_assembly(repository, signal_ids=COHORT)
    assert tuple(repository.match_ids or ()) == COHORT


def test_summary_selection_accepts_only_touched_events() -> None:
    repository = EmptyEventRepository()
    repository.events_awaiting_summary(limit=10, max_age_hours=24, event_ids=(COHORT[0],))
    assert repository.summary_ids == (COHORT[0],)


def test_duplicate_does_not_trigger_global_backlog() -> None:
    repository = EmptyDedupeRepository()
    run_dedupe(repository, signal_ids=COHORT)
    assert not set(repository.requested or ()) & set(HISTORY)


def test_three_signal_cohort_has_no_historical_ids() -> None:
    assert len(COHORT) == 3
    assert not set(COHORT) & set(HISTORY)
