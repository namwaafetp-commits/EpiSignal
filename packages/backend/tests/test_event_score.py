from datetime import UTC, datetime, timedelta
from uuid import uuid4

from episignal_backend.db.types import CredibilityTier, LocationRole, Precision
from episignal_backend.events.documents import (
    LocationForMatching,
    ScoreBreakdown,
    SignalForMatching,
)
from episignal_backend.events.score import (
    DEFAULT_EARLY_SIGNAL_WEIGHTS,
    early_signal_score,
)


def _make_signal(
    *,
    source_id=None,
    source_is_official=False,
    credibility_tier=CredibilityTier.MEDIUM,
    published_at=None,
    locations=(),
) -> SignalForMatching:
    now = datetime.now(UTC)
    pub = published_at if published_at is not None else now
    return SignalForMatching(
        signal_id=uuid4(),
        disease_id=uuid4(),
        source_id=source_id or uuid4(),
        source_is_official=source_is_official,
        credibility_tier=credibility_tier,
        published_at=pub,
        first_seen_at=pub,
        locations=locations,
    )


def test_early_signal_score_recency():
    now = datetime.now(UTC)
    sig_today = _make_signal(published_at=now)
    sig_old = _make_signal(published_at=now - timedelta(days=30))

    score_today = early_signal_score([sig_today], now=now)
    score_old = early_signal_score([sig_old], now=now)

    assert score_today.components["recency"] > score_old.components["recency"]
    assert score_today.total > score_old.total


def test_early_signal_score_distinct_sources():
    now = datetime.now(UTC)
    single_source = uuid4()
    five_signals_one_source = [
        _make_signal(source_id=single_source, published_at=now) for _ in range(5)
    ]
    five_signals_five_sources = [
        _make_signal(source_id=uuid4(), published_at=now) for _ in range(5)
    ]

    score_one = early_signal_score(five_signals_one_source, now=now)
    score_five = early_signal_score(five_signals_five_sources, now=now)

    assert score_five.components["sources"] > score_one.components["sources"]
    assert score_five.total > score_one.total


def test_early_signal_score_saturates_at_high_volume():
    now = datetime.now(UTC)
    fifty_signals = [
        _make_signal(source_id=uuid4(), published_at=now - timedelta(hours=i)) for i in range(50)
    ]
    score_fifty = early_signal_score(fifty_signals, now=now)

    assert 0.0 <= score_fifty.total <= 1.0
    for comp in score_fifty.components.values():
        assert 0.0 <= comp <= 1.0


def test_early_signal_score_bounds_and_weights():
    now = datetime.now(UTC)
    loc = LocationForMatching(
        location_role=LocationRole.PRIMARY,
        precision=Precision.PLACE,
        country_code="CD",
        admin1="North Kivu",
        place_name="Beni",
        latitude=0.49,
        longitude=29.47,
    )
    sig = _make_signal(published_at=now, locations=(loc,))
    score = early_signal_score([sig], now=now, weights=DEFAULT_EARLY_SIGNAL_WEIGHTS)

    assert isinstance(score, ScoreBreakdown)
    assert 0.0 <= score.total <= 1.0
