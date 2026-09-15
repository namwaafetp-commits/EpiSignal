from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from episignal_backend.ai.documents import ModelSpec
from episignal_backend.db.types import AiProvider, AiPurpose
from episignal_backend.events.documents import EventForSummary, SummarySource
from episignal_backend.events.summarize import SummaryWiring
from episignal_backend.schedule import stages
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

    assert set(runners) == set(DAILY_CHAIN)


def _summary_event(
    *,
    last_summarized_at: datetime | None = None,
    latest_observation: dict[str, object] | None = None,
    previous_counts: dict[str, object] | None = None,
    unsummarized_articles: int = 0,
    article_text: str = "An outbreak investigation is underway.",
) -> EventForSummary:
    return EventForSummary(
        event_id=uuid4(),
        public_id="EVT-TEST",
        latest_observation=latest_observation,
        previous_counts=previous_counts,
        unsummarized_articles=unsummarized_articles,
        last_summarized_at=last_summarized_at,
        sources=(
            SummarySource(
                signal_id=uuid4(),
                title="Report",
                source_name="Source",
                article_text=article_text,
            ),
        ),
    )


def test_summary_stage_reports_why_due_events_were_skipped(monkeypatch) -> None:
    now = datetime.now(UTC)
    events = (
        _summary_event(),
        _summary_event(article_text="   "),
        _summary_event(last_summarized_at=now, unsummarized_articles=0),
    )

    class FakeEventRepository:
        def __init__(self, session) -> None:
            self.commits = 0

        def events_awaiting_summary(self, **kwargs):
            return events

        def commit(self) -> None:
            self.commits += 1

    class FakeAiRepository:
        def __init__(self, session) -> None:
            pass

        def models(self):
            return ()

    @contextmanager
    def fake_session_scope():
        yield object()

    monkeypatch.setattr(
        stages,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "event_match_batch_size": 100,
                "resummary_max_age_hours": 24,
                "resummary_new_article_count": 3,
            },
        )(),
    )
    monkeypatch.setattr(stages, "session_scope", fake_session_scope)
    monkeypatch.setattr(stages, "SqlAlchemyEventRepository", FakeEventRepository)
    monkeypatch.setattr(stages, "SqlAlchemyAiRepository", FakeAiRepository)
    monkeypatch.setattr(
        stages, "configure_summary", lambda settings, specs: SummaryWiring(None, None)
    )

    counts = stages._summarize(type("Cohort", (), {"touched_event_ids": ()})())

    assert counts["examined"] == 3
    assert counts["skipped"] == 3
    assert counts["skipped_no_change"] == 1
    assert counts["skipped_no_model"] == 1
    assert counts["skipped_no_sources"] == 1


def test_summary_stage_sends_new_article_without_structured_observation_to_model(
    monkeypatch,
) -> None:
    event = _summary_event()
    requests: list[EventForSummary] = []
    summary_spec = ModelSpec(
        id=uuid4(),
        tier=1,
        model_id="deepseek/deepseek-v4-flash-0731",
        label="DeepSeek V4 Flash",
        provider=AiProvider.OPENROUTER,
        purpose=AiPurpose.EVENT_SUMMARY,
        prompt_price_per_million=Decimal("0"),
        completion_price_per_million=Decimal("0"),
    )

    class FakeEventRepository:
        def __init__(self, session) -> None:
            self.stored = 0

        def events_awaiting_summary(self, **kwargs):
            return (event,)

        def record_ai_request(self, record) -> None:
            pass

        def store_summary(self, **kwargs) -> None:
            self.stored += 1

        def commit(self) -> None:
            pass

    class FakeAiRepository:
        def __init__(self, session) -> None:
            pass

        def models(self):
            return (summary_spec,)

    @contextmanager
    def fake_session_scope():
        yield object()

    def fake_summary(model, spec, *, event, sources):
        requests.append(event)
        return stages.SummaryResult(
            outcome=stages.SummaryOutcome.REJECTED,
            attempt=None,
        )

    monkeypatch.setattr(
        stages,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "event_match_batch_size": 100,
                "resummary_max_age_hours": 24,
                "resummary_new_article_count": 3,
            },
        )(),
    )
    monkeypatch.setattr(stages, "session_scope", fake_session_scope)
    monkeypatch.setattr(stages, "SqlAlchemyEventRepository", FakeEventRepository)
    monkeypatch.setattr(stages, "SqlAlchemyAiRepository", FakeAiRepository)
    monkeypatch.setattr(
        stages, "configure_summary", lambda settings, specs: SummaryWiring(object(), summary_spec)
    )
    monkeypatch.setattr(stages, "run_summary", fake_summary)

    counts = stages._summarize(type("Cohort", (), {"touched_event_ids": ()})())

    assert requests == [event]
    assert event.latest_observation is None
    assert event.previous_counts is None
    assert counts["summarized"] == 0
    assert counts["failed"] == 1
