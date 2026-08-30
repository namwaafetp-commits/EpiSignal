"""The ambiguous-event LLM judge and its wiring in the assembly.

The deterministic engine refuses an ambiguous match (single candidate between
the review threshold and the auto threshold); the judge decides same_event.
Uncertainty and unavailability must prefer a new event, because a false merge
is worse than a duplicate event.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from episignal_backend.ai.documents import ChatResponse
from episignal_backend.ai.protocol import ModelUnavailable
from episignal_backend.db.types import (
    AiPurpose,
    LocationRole,
    Precision,
)
from episignal_backend.events.documents import (
    CandidateEvent,
    LocationForMatching,
    MatchAction,
    SignalForMatching,
    StoryCluster,
)
from episignal_backend.events.judge import (
    JudgeOutcome,
    run_judge,
)
from episignal_backend.events.match import decide, match_score
from test_event_assemble import FakeAssemblyRepository, _make_signal


def _signal(disease_id: UUID, *, published_at: datetime) -> SignalForMatching:
    return _make_signal(disease_id=disease_id, published_at=published_at)


def _cluster(disease_id: UUID, *, admin1: str = "Chiang Mai") -> StoryCluster:
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="TH",
        admin1=admin1,
        place_name=admin1,
        latitude=18.79,
        longitude=98.98,
    )
    return StoryCluster(
        signals=(_make_signal(disease_id=disease_id, loc=loc, published_at=datetime.now(UTC)),)
    )


def _country_candidate(
    disease_id: UUID, *, title: str = "Dengue outbreak in Thailand"
) -> CandidateEvent:
    """A country-level candidate: scores below an identical-place candidate."""
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.COUNTRY,
        country_code="TH",
        latitude=15.87,
        longitude=100.99,
    )
    return CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(loc,),
        first_signal_at=datetime.now(UTC) - timedelta(days=3),
        last_updated_at=datetime.now(UTC) - timedelta(days=1),
        title=title,
        recent_source_titles=(title,),
    )


def test_a_single_candidate_in_the_ambiguous_band_is_ambiguous() -> None:
    disease_id = uuid4()
    cluster = _cluster(disease_id)
    candidate = _country_candidate(disease_id)
    score = match_score(cluster, candidate)
    assert score < 0.95  # a country-level match must not auto-attach

    decision = decide(
        cluster,
        [candidate],
        threshold=score + 0.05,
        review_threshold=score - 0.05,
    )

    assert decision.action is MatchAction.AMBIGUOUS
    assert decision.event_id == candidate.event_id
    assert decision.match_score is not None


def test_a_candidate_below_the_review_threshold_is_still_a_new_event() -> None:
    disease_id = uuid4()
    cluster = _cluster(disease_id)
    candidate = _country_candidate(disease_id)
    score = match_score(cluster, candidate)

    decision = decide(
        cluster,
        [candidate],
        threshold=0.95,
        review_threshold=score + 0.05,
    )

    assert decision.action is MatchAction.CREATE
    assert decision.event_id is None


def test_ambiguity_is_disabled_when_no_review_threshold_is_given() -> None:
    disease_id = uuid4()
    cluster = _cluster(disease_id)
    candidate = _country_candidate(disease_id)
    # Without a review threshold, the ambiguous band does not exist and the
    # old behavior is preserved exactly.
    decision = decide(cluster, [candidate], threshold=0.95)

    assert decision.action is MatchAction.CREATE


def test_two_qualifiers_still_refuse() -> None:
    disease_id = uuid4()
    cluster = _cluster(disease_id)
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="TH",
        admin1="Chiang Mai",
        place_name="Chiang Mai",
        latitude=18.79,
        longitude=98.98,
    )
    first = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(loc,),
        first_signal_at=datetime.now(UTC) - timedelta(days=3),
        last_updated_at=datetime.now(UTC) - timedelta(days=1),
    )
    second = CandidateEvent(
        event_id=uuid4(),
        disease_id=disease_id,
        locations=(loc,),
        first_signal_at=datetime.now(UTC) - timedelta(days=3),
        last_updated_at=datetime.now(UTC) - timedelta(days=1),
    )
    decision = decide(
        cluster,
        [first, second],
        threshold=0.5,
        review_threshold=0.4,
    )

    assert decision.action is MatchAction.REFUSE


class FakeJudgeModel:
    def __init__(self, content: str | None = None, refuse: bool = False) -> None:
        self._content = content
        self._refuse = refuse
        self.calls = 0

    def complete(self, request) -> object:
        self.calls += 1
        if self._refuse:
            raise ModelUnavailable("refused")
        return ChatResponse(content=self._content or "{}", latency_ms=5)


_SAME_EVENT = (
    '{"same_event": true, "confidence": 0.9, "reason": "Same dengue outbreak in Chiang Mai with '
    'follow-up case count."}'
)
_DIFFERENT_EVENT = (
    '{"same_event": false, "confidence": 0.8, "reason": "Different province of the same disease."}'
)


def test_the_judge_accepts_a_same_event_answer() -> None:
    model = FakeJudgeModel(_SAME_EVENT)
    result = run_judge(
        model,
        _judge_spec(),
        new_title="Dengue cases rise in Chiang Mai",
        new_snippet="The provincial health office reported more cases.",
        event_title="Dengue outbreak in Chiang Mai",
        event_context="Chiang Mai, TH",
        recent_source_titles=("Dengue outbreak in Chiang Mai",),
    )

    assert result.outcome is JudgeOutcome.ACCEPTED
    assert result.judgement is not None
    assert result.judgement.same_event is True
    assert model.calls == 1


def test_the_judge_accepts_a_different_event_answer() -> None:
    model = FakeJudgeModel(_DIFFERENT_EVENT)
    result = run_judge(
        model,
        _judge_spec(),
        new_title="Dengue cases rise in Phuket",
        new_snippet="The provincial health office reported more cases.",
        event_title="Dengue outbreak in Chiang Mai",
        event_context="Chiang Mai, TH",
        recent_source_titles=("Dengue outbreak in Chiang Mai",),
    )

    assert result.outcome is JudgeOutcome.ACCEPTED
    assert result.judgement is not None
    assert result.judgement.same_event is False


def test_an_unavailable_judge_is_unavailable() -> None:
    model = FakeJudgeModel(refuse=True)
    result = run_judge(
        model,
        _judge_spec(),
        new_title="Dengue cases rise in Chiang Mai",
        new_snippet="More cases.",
        event_title="Dengue outbreak in Chiang Mai",
        event_context="Chiang Mai, TH",
        recent_source_titles=(),
    )

    assert result.outcome is JudgeOutcome.UNAVAILABLE
    assert result.judgement is None


def test_judge_rejects_malformed_json() -> None:
    model = FakeJudgeModel("not json")
    result = run_judge(
        model,
        _judge_spec(),
        new_title="Dengue cases rise in Chiang Mai",
        new_snippet="More cases.",
        event_title="Dengue outbreak in Chiang Mai",
        event_context="Chiang Mai, TH",
        recent_source_titles=(),
    )

    assert result.outcome is JudgeOutcome.REJECTED
    assert result.judgement is None


def _judge_spec():
    from decimal import Decimal

    from episignal_backend.ai.documents import ModelSpec

    return ModelSpec(
        id=uuid4(),
        tier=1,
        model_id="meta-llama/llama-3.1-8b-instruct",
        label="Llama 3.1 8B Instruct",
        prompt_price_per_million=Decimal("0.02"),
        completion_price_per_million=Decimal("0.04"),
    )


def _ambiguous_scenario() -> tuple[StoryCluster, CandidateEvent]:
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="TH",
        admin1="Chiang Mai",
        place_name="Chiang Mai",
        latitude=18.79,
        longitude=98.98,
    )
    cluster = StoryCluster(
        signals=(_make_signal(disease_id=disease_id, loc=loc, published_at=now),)
    )
    candidate = _country_candidate(disease_id, title="Dengue outbreak in Thailand")
    score = match_score(cluster, candidate)
    assert score < 0.95
    return cluster, candidate


def test_an_ambiguous_match_attaches_when_the_judge_says_same_event() -> None:
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="TH",
        admin1="Chiang Mai",
        place_name="Chiang Mai",
        latitude=18.79,
        longitude=98.98,
    )
    candidate = _country_candidate(disease_id, title="Dengue outbreak in Thailand")
    sig = _make_signal(disease_id=disease_id, loc=loc, published_at=now)
    repo = FakeAssemblyRepository([sig], {disease_id: [candidate]})

    from episignal_backend.events.assemble import run_event_assembly

    summary = run_event_assembly(
        repo,
        now=now,
        match_threshold=0.95,
        review_threshold=0.4,
        judge_model=FakeJudgeModel(_SAME_EVENT),
        judge_spec=_judge_spec(),
    )

    assert summary.events_created == 0
    assert summary.signals_attached == 1
    assert summary.ambiguous_judged == 1
    assert summary.ambiguous_attached == 1
    assert repo.attached_signals[0][0] == candidate.event_id
    assert any(req.purpose is AiPurpose.EVENT_MATCH_JUDGE for req in repo.ai_requests)


def test_an_ambiguous_match_creates_a_new_event_when_the_judge_disagrees() -> None:
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="TH",
        admin1="Chiang Mai",
        place_name="Chiang Mai",
        latitude=18.79,
        longitude=98.98,
    )
    candidate = _country_candidate(disease_id, title="Dengue outbreak in Thailand")
    sig = _make_signal(disease_id=disease_id, loc=loc, published_at=now)
    repo = FakeAssemblyRepository([sig], {disease_id: [candidate]})

    from episignal_backend.events.assemble import run_event_assembly

    summary = run_event_assembly(
        repo,
        now=now,
        match_threshold=0.95,
        review_threshold=0.4,
        judge_model=FakeJudgeModel(_DIFFERENT_EVENT),
        judge_spec=_judge_spec(),
    )

    assert summary.events_created == 1
    assert summary.ambiguous_judged == 1
    assert summary.ambiguous_attached == 0
    assert repo.created_events
    assert repo.attached_signals[0][0] == repo.created_events[0].event_id


def test_an_ambiguous_match_without_a_judge_prefers_a_new_event() -> None:
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="TH",
        admin1="Chiang Mai",
        place_name="Chiang Mai",
        latitude=18.79,
        longitude=98.98,
    )
    candidate = _country_candidate(disease_id, title="Dengue outbreak in Thailand")
    sig = _make_signal(disease_id=disease_id, loc=loc, published_at=now)
    repo = FakeAssemblyRepository([sig], {disease_id: [candidate]})

    from episignal_backend.events.assemble import run_event_assembly

    summary = run_event_assembly(
        repo,
        now=now,
        match_threshold=0.95,
        review_threshold=0.4,
        judge_model=None,
        judge_spec=None,
    )

    assert summary.events_created == 1
    assert summary.ambiguous_judged == 0


def test_an_unavailable_judge_prefers_a_new_event() -> None:
    now = datetime.now(UTC)
    disease_id = uuid4()
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="TH",
        admin1="Chiang Mai",
        place_name="Chiang Mai",
        latitude=18.79,
        longitude=98.98,
    )
    candidate = _country_candidate(disease_id, title="Dengue outbreak in Thailand")
    sig = _make_signal(disease_id=disease_id, loc=loc, published_at=now)
    repo = FakeAssemblyRepository([sig], {disease_id: [candidate]})

    from episignal_backend.events.assemble import run_event_assembly

    summary = run_event_assembly(
        repo,
        now=now,
        match_threshold=0.95,
        review_threshold=0.4,
        judge_model=FakeJudgeModel(refuse=True),
        judge_spec=_judge_spec(),
    )

    assert summary.events_created == 1
    assert summary.ambiguous_judged == 1
