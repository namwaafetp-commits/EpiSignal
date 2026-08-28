from datetime import UTC, datetime, timedelta
from uuid import uuid4

from episignal_backend.ai.schema import BriefPoint, BriefSlot, Extraction
from episignal_backend.db.types import CredibilityTier, LocationRole, Precision, SignalType
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


def test_evidence_score_official_outscores_informal():
    from episignal_backend.events.score import evidence_score

    now = datetime.now(UTC)
    official_sig = _make_signal(
        source_is_official=True,
        credibility_tier=CredibilityTier.OFFICIAL,
        published_at=now,
    )
    ten_informal = [
        _make_signal(
            source_is_official=False,
            credibility_tier=CredibilityTier.MEDIUM,
            published_at=now,
        )
        for _ in range(10)
    ]

    score_off = evidence_score([official_sig])
    score_inf = evidence_score(ten_informal)

    assert score_off.components["official"] == 1.0
    assert score_inf.components["official"] == 0.0
    assert score_off.components["official"] > score_inf.components["official"]


def test_evidence_score_contradictory_totals_lower_consistency():
    from episignal_backend.ai.schema import (
        BriefPoint,
        BriefSlot,
        Epidemiology,
        GroundedCount,
    )
    from episignal_backend.events.score import evidence_score

    now = datetime.now(UTC)

    def _brief(text: str) -> tuple[BriefPoint, ...]:
        return (
            BriefPoint(slot=BriefSlot.WHAT_WHERE, text="Outbreak", reported=True),
            BriefPoint(slot=BriefSlot.COUNTS, text=text, reported=True),
            BriefPoint(slot=BriefSlot.TIMING, text="No date", reported=False),
            BriefPoint(slot=BriefSlot.SPREAD, text="No spread", reported=False),
            BriefPoint(slot=BriefSlot.REPORTING, text="No reporting", reported=False),
        )

    # Consistent reporting: 50 -> 60
    ext_1 = Extraction(
        signal_type=SignalType.OUTBREAK_REPORT,
        title_english="50 cases reported",
        brief=_brief("50 cases"),
        epidemiology=Epidemiology(
            total_cases=GroundedCount(value=50, source_span="50 cases reported")
        ),
        confidence=0.9,
    )
    ext_2 = Extraction(
        signal_type=SignalType.OUTBREAK_REPORT,
        title_english="60 cases reported",
        brief=_brief("60 cases"),
        epidemiology=Epidemiology(
            total_cases=GroundedCount(value=60, source_span="60 cases total")
        ),
        confidence=0.9,
    )
    sig_1 = SignalForMatching(
        signal_id=uuid4(),
        disease_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.HIGH,
        published_at=now - timedelta(days=2),
        first_seen_at=now - timedelta(days=2),
        extraction=ext_1,
    )
    sig_2 = SignalForMatching(
        signal_id=uuid4(),
        disease_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.HIGH,
        published_at=now,
        first_seen_at=now,
        extraction=ext_2,
    )

    # Contradictory reporting: 500 -> 5
    ext_contradict = Extraction(
        signal_type=SignalType.OUTBREAK_REPORT,
        title_english="5 cases reported",
        brief=_brief("5 cases"),
        epidemiology=Epidemiology(total_cases=GroundedCount(value=5, source_span="5 cases only")),
        confidence=0.9,
    )
    ext_prior = Extraction(
        signal_type=SignalType.OUTBREAK_REPORT,
        title_english="500 cases reported",
        brief=_brief("500 cases"),
        epidemiology=Epidemiology(
            total_cases=GroundedCount(value=500, source_span="500 cases reported")
        ),
        confidence=0.9,
    )
    sig_contra_1 = SignalForMatching(
        signal_id=uuid4(),
        disease_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.HIGH,
        published_at=now - timedelta(days=2),
        first_seen_at=now - timedelta(days=2),
        extraction=ext_prior,
    )
    sig_contra_2 = SignalForMatching(
        signal_id=uuid4(),
        disease_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.HIGH,
        published_at=now,
        first_seen_at=now,
        extraction=ext_contradict,
    )

    score_consistent = evidence_score([sig_1, sig_2])
    score_contra = evidence_score([sig_contra_1, sig_contra_2])

    assert score_consistent.components["consistency"] > score_contra.components["consistency"]


def test_scores_are_independent():
    from episignal_backend.events.score import early_signal_score, evidence_score

    now = datetime.now(UTC)
    sig_today = _make_signal(published_at=now)
    sig_30d_ago = _make_signal(published_at=now - timedelta(days=30))

    # Changing recency (early-signal only) must change early_signal_score
    early_today = early_signal_score([sig_today], now=now)
    early_old = early_signal_score([sig_30d_ago], now=now)
    assert early_today.total != early_old.total

    # But evidence_score on both must be identical (recency does not enter evidence_score)
    ev_today = evidence_score([sig_today])
    ev_old = evidence_score([sig_30d_ago])
    assert ev_today.total == ev_old.total


def test_verification_status_derived_from_sources_only():
    from episignal_backend.db.types import VerificationStatus
    from episignal_backend.events.score import verification_status

    now = datetime.now(UTC)

    # 1. Official source -> OFFICIALLY_CONFIRMED
    sig_official = _make_signal(
        source_is_official=True,
        credibility_tier=CredibilityTier.OFFICIAL,
        published_at=now,
    )
    assert verification_status([sig_official]) == VerificationStatus.OFFICIALLY_CONFIRMED

    # 2. High credibility source -> HIGH_CREDIBILITY
    sig_high = _make_signal(
        source_is_official=False,
        credibility_tier=CredibilityTier.HIGH,
        published_at=now,
    )
    assert verification_status([sig_high]) == VerificationStatus.HIGH_CREDIBILITY

    # 3. Medium/low credibility source with perfect AI extraction -> still SIGNAL
    sig_informal = SignalForMatching(
        signal_id=uuid4(),
        disease_id=uuid4(),
        source_id=uuid4(),
        source_is_official=False,
        credibility_tier=CredibilityTier.MEDIUM,
        published_at=now,
        first_seen_at=now,
        extraction=Extraction(
            signal_type=SignalType.OUTBREAK_REPORT,
            title_english="Confirmed outbreak by blog",
            brief=(
                BriefPoint(slot=BriefSlot.WHAT_WHERE, text="Outbreak", reported=True),
                BriefPoint(slot=BriefSlot.COUNTS, text="No counts", reported=False),
                BriefPoint(slot=BriefSlot.TIMING, text="No date", reported=False),
                BriefPoint(slot=BriefSlot.SPREAD, text="No spread", reported=False),
                BriefPoint(slot=BriefSlot.REPORTING, text="Blog post", reported=True),
            ),
            confidence=1.0,
        ),
    )
    assert verification_status([sig_informal]) == VerificationStatus.SIGNAL
