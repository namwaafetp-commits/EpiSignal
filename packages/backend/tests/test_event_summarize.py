"""The event summarizer: material-change detection, source picking, and the pass.

A summary is regenerated only when the counts the last summary was written
against no longer match the latest observation, when enough new articles
arrived, or when the summary is simply too old. A duplicate report that adds no
new numbers must not trigger a re-summary.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from episignal_backend.events.documents import SummarySource
from episignal_backend.events.summarize import (
    SummaryOutcome,
    pick_representative_sources,
    run_summary,
    should_resummarize,
)


class FakeSummaryModel:
    def __init__(self, content: str | None = None, refuse: bool = False) -> None:
        self._content = content
        self._refuse = refuse
        self.calls = 0

    def complete(self, request) -> object:
        from episignal_backend.ai.documents import ChatResponse
        from episignal_backend.ai.protocol import ModelUnavailable

        self.calls += 1
        if self._refuse:
            raise ModelUnavailable("refused")
        return ChatResponse(content=self._content or "{}", latency_ms=5)


def _counts(total: int | None, deaths: int | None) -> dict[str, object]:
    return {
        "data_as_of": "2026-08-25",
        "confirmed_cases": None,
        "total_cases": total,
        "deaths": deaths,
        "new_cases": None,
        "new_deaths": None,
    }


def test_a_never_summarized_event_is_due() -> None:
    assert should_resummarize(
        last_summarized_at=None,
        latest_observation=_counts(42, 3),
        previous_counts=None,
        unsummarized_articles=1,
    )


def test_a_material_case_count_change_is_due() -> None:
    assert should_resummarize(
        last_summarized_at=datetime.now(UTC) - timedelta(hours=1),
        latest_observation=_counts(68, 3),
        previous_counts=_counts(42, 3),
        unsummarized_articles=1,
    )


def test_a_material_death_count_change_is_due() -> None:
    assert should_resummarize(
        last_summarized_at=datetime.now(UTC) - timedelta(hours=1),
        latest_observation=_counts(68, 5),
        previous_counts=_counts(68, 3),
        unsummarized_articles=1,
    )


def test_a_duplicate_report_with_no_new_counts_is_not_due() -> None:
    assert not should_resummarize(
        last_summarized_at=datetime.now(UTC) - timedelta(hours=1),
        latest_observation=_counts(68, 3),
        previous_counts=_counts(68, 3),
        unsummarized_articles=1,
    )


def test_enough_new_articles_trigger_a_resummary() -> None:
    assert should_resummarize(
        last_summarized_at=datetime.now(UTC) - timedelta(hours=1),
        latest_observation=_counts(68, 3),
        previous_counts=_counts(68, 3),
        unsummarized_articles=3,
        new_article_count=3,
    )


def test_few_new_articles_with_no_count_change_do_not_trigger() -> None:
    assert not should_resummarize(
        last_summarized_at=datetime.now(UTC) - timedelta(hours=1),
        latest_observation=_counts(68, 3),
        previous_counts=_counts(68, 3),
        unsummarized_articles=2,
        new_article_count=3,
    )


def test_a_summary_older_than_the_max_age_is_refreshed() -> None:
    assert should_resummarize(
        last_summarized_at=datetime.now(UTC) - timedelta(hours=25),
        latest_observation=_counts(68, 3),
        previous_counts=_counts(68, 3),
        unsummarized_articles=0,
        max_age_hours=24,
    )


def _source(
    title: str,
    *,
    official: bool = False,
    brief: int = 0,
    published_at: datetime | None = None,
) -> SummarySource:
    from episignal_backend.ai.schema import BriefPoint, BriefSlot

    points = tuple(
        BriefPoint(slot=BriefSlot.COUNTS, text=f"{title} brief", reported=True)
        for _ in range(brief)
    )
    return SummarySource(
        signal_id=uuid4(),
        title=title,
        source_name=title,
        is_official=official,
        published_at=published_at,
        brief=points,
    )


def test_official_sources_are_picked_first() -> None:
    sources = (
        _source("Ministry of Health", official=True),
        _source("Local News"),
        _source("Reuters"),
    )

    picked = pick_representative_sources(sources, max_sources=2)

    assert picked[0].source_name == "Ministry of Health"
    assert len(picked) == 2


def test_brief_carrying_sources_precede_silent_ones() -> None:
    sources = (
        _source("No counts", brief=0),
        _source("With counts", brief=5),
    )

    picked = pick_representative_sources(sources, max_sources=2)

    assert picked[0].source_name == "With counts"


def test_picking_respects_the_maximum() -> None:
    sources = tuple(_source(f"S{i}") for i in range(10))
    assert len(pick_representative_sources(sources, max_sources=6)) == 6


def test_picking_preserves_the_newest_useful_report_after_official_sources() -> None:
    old = datetime(2026, 8, 25, tzinfo=UTC)
    newest = datetime(2026, 8, 30, tzinfo=UTC)
    sources = (
        _source("Old official", official=True, published_at=old, brief=5),
        _source("Older official", official=True, published_at=old - timedelta(days=1), brief=5),
        _source("Newest useful report", published_at=newest, brief=5),
    )

    picked = pick_representative_sources(sources, max_sources=2)

    assert picked[0].source_name == "Old official"
    assert any(source.source_name == "Newest useful report" for source in picked)


_SUMMARY_JSON = """{
  "headline": "Dengue outbreak reported in Chiang Mai",
  "summary": "Health authorities reported an ongoing dengue outbreak in Chiang Mai.",
  "status": "ongoing",
  "latest_development": "Case count rose to 68.",
  "uncertainties": ["Reporting may lag behind the latest case count."]
}"""


def _summary_input():
    from episignal_backend.events.documents import EventForSummary

    return EventForSummary(
        event_id=uuid4(),
        public_id="EVT-00000001",
        disease="dengue",
        location="Chiang Mai",
        latest_observation=_counts(68, 3),
        sources=(
            SummarySource(
                signal_id=uuid4(),
                title="MoH report",
                source_name="Ministry of Health",
                is_official=True,
            ),
        ),
    )


def test_the_summarizer_accepts_a_valid_verdict() -> None:
    model = FakeSummaryModel(_SUMMARY_JSON)
    result = run_summary(model, _summary_spec(), event=_summary_input(), sources=(_source("x"),))

    assert result.outcome is SummaryOutcome.ACCEPTED
    assert result.verdict is not None
    assert result.verdict.headline == "Dengue outbreak reported in Chiang Mai"
    assert result.verdict.status.value == "ongoing"
    assert model.calls == 1


def test_the_summarizer_rejects_malformed_output() -> None:
    model = FakeSummaryModel("not json")
    result = run_summary(model, _summary_spec(), event=_summary_input(), sources=(_source("x"),))

    assert result.outcome is SummaryOutcome.REJECTED
    assert result.verdict is None


def test_an_unavailable_summarizer_is_unavailable() -> None:
    model = FakeSummaryModel(refuse=True)
    result = run_summary(model, _summary_spec(), event=_summary_input(), sources=(_source("x"),))

    assert result.outcome is SummaryOutcome.UNAVAILABLE
    assert result.verdict is None


def _summary_spec():
    from decimal import Decimal

    from episignal_backend.ai.documents import ModelSpec

    return ModelSpec(
        id=uuid4(),
        tier=1,
        model_id="deepseek/deepseek-v4-flash-0731",
        label="DeepSeek V4 Flash",
        prompt_price_per_million=Decimal("0.03"),
        completion_price_per_million=Decimal("0.10"),
    )
