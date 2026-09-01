"""The event summarizer: the EpiSignal flash brief and its change gate."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from episignal_backend.events.documents import EventForSummary, SummarySource
from episignal_backend.events.summarize import (
    SummaryOutcome,
    SummaryTrajectory,
    pick_representative_sources,
    render_event_flash_brief,
    run_summary,
    should_resummarize,
    unique_summary_candidates,
)


class FakeSummaryModel:
    def __init__(self, content: str | None = None, refuse: bool = False) -> None:
        self._content = content
        self._refuse = refuse
        self.calls = 0
        self.requests = []

    def complete(self, request) -> object:
        from episignal_backend.ai.documents import ChatResponse
        from episignal_backend.ai.protocol import ModelUnavailable

        self.calls += 1
        self.requests.append(request)
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


def test_a_new_source_with_no_material_change_does_not_trigger_a_resummary() -> None:
    assert not should_resummarize(
        last_summarized_at=datetime.now(UTC) - timedelta(hours=1),
        latest_observation=_counts(68, 3),
        previous_counts=_counts(68, 3),
        unsummarized_articles=99,
        new_article_count=1,
    )


def test_an_old_summary_with_no_material_change_does_not_trigger_a_resummary() -> None:
    assert not should_resummarize(
        last_summarized_at=datetime.now(UTC) - timedelta(hours=25),
        latest_observation=_counts(68, 3),
        previous_counts=_counts(68, 3),
        unsummarized_articles=0,
        max_age_hours=24,
    )


def test_a_new_geographic_extent_is_a_material_change() -> None:
    previous = _counts(68, 3)
    latest = previous | {"geographic_extent": "Chiang Mai and Phuket"}
    assert should_resummarize(
        last_summarized_at=datetime.now(UTC) - timedelta(hours=1),
        latest_observation=latest,
        previous_counts=previous,
    )


def test_one_summarization_run_keeps_one_candidate_per_event() -> None:
    event_id = uuid4()
    duplicate = EventForSummary(event_id=event_id, public_id="epi-1")
    other = EventForSummary(event_id=uuid4(), public_id="epi-2")

    candidates = unique_summary_candidates((duplicate, duplicate, other))

    assert candidates == (duplicate, other)
    assert len({candidate.event_id for candidate in candidates}) == 2


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
  "headline": "Dengue Outbreak: Chiang Mai — Increasing",
  "trajectory": "Increasing",
  "snapshot": {
    "cases": "68 total cases",
    "deaths": "3 deaths",
    "cfr": null,
    "geographic_extent": "Chiang Mai"
  },
  "key_driver": "Ongoing local transmission reported by health authorities.",
  "response": "Case investigation and vaccination activities are underway.",
  "risk": "Risk remains regional because transmission is reported only in Chiang Mai."
}"""


def _summary_input():
    from episignal_backend.events.documents import EventForSummary

    return EventForSummary(
        event_id=uuid4(),
        public_id="EVT-00000001",
        disease="dengue",
        location="Chiang Mai",
        latest_observation=_counts(68, 3),
        observations=(
            {"source_name": "official", "confirmed_cases": 42},
            {"source_name": "local", "confirmed_cases": 68},
        ),
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
    assert result.verdict.headline == "Dengue Outbreak: Chiang Mai — Increasing"
    assert result.verdict.trajectory is SummaryTrajectory.INCREASING
    assert result.verdict.snapshot.cases == "68 total cases"
    assert result.verdict.risk.startswith("Risk remains regional")
    assert render_event_flash_brief(result.verdict) == (
        "Dengue Outbreak: Chiang Mai — Increasing\n\n"
        "The Snapshot:\n"
        "68 total cases | 3 deaths | Chiang Mai\n\n"
        "Key Driver:\n"
        "Ongoing local transmission reported by health authorities.\n\n"
        "Response:\n"
        "Case investigation and vaccination activities are underway.\n\n"
        "Public/Global Risk:\n"
        "Risk remains regional because transmission is reported only in Chiang Mai."
    )
    assert model.calls == 1


def test_the_summary_prompt_requires_the_epi_signal_flash_brief() -> None:
    model = FakeSummaryModel(_SUMMARY_JSON)
    run_summary(model, _summary_spec(), event=_summary_input(), sources=(_source("x"),))

    request = model.requests[0]
    assert "The Snapshot:" in request.system
    assert "Public/Global Risk:" in request.system
    assert '"trajectory"' in request.system
    assert '"snapshot"' in request.system
    assert "latest_development" not in request.system
    assert "uncertainties" not in request.system
    payload = json.loads(request.user)
    assert payload["observations"] == [
        {"source_name": "official", "confirmed_cases": 42},
        {"source_name": "local", "confirmed_cases": 68},
    ]


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
