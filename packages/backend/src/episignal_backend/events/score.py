"""Dual scoring engine and verification status derivation.

Pure functions for computing early_signal_score, evidence_score, and
verification_status.

Neither score reads the other. This module imports neither SQLAlchemy nor httpx.
"""

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from episignal_backend.events.cluster import precision_weight
from episignal_backend.events.documents import ScoreBreakdown, SignalForMatching

DEFAULT_EARLY_SIGNAL_WEIGHTS: dict[str, float] = {
    "recency": 0.25,
    "velocity": 0.20,
    "sources": 0.25,
    "spread": 0.15,
    "precision": 0.15,
}


def _signal_timestamp(sig: SignalForMatching) -> datetime:
    ts = sig.published_at if sig.published_at is not None else sig.first_seen_at
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise ValueError("Timezone-aware datetime required for score computation")
    return ts


def _compute_recency(signals: Sequence[SignalForMatching], now: datetime) -> float:
    newest = max(_signal_timestamp(s) for s in signals)
    gap_days = max(0.0, (now - newest).total_seconds() / 86400.0)
    # Exponential decay with half-life ~ 14 days
    return math.exp(-gap_days / 14.0)


def _compute_velocity(signals: Sequence[SignalForMatching]) -> float:
    if not signals:
        return 0.0
    timestamps = [_signal_timestamp(s) for s in signals]
    span_days = max(1.0, (max(timestamps) - min(timestamps)).total_seconds() / 86400.0)
    rate = len(signals) / span_days
    # Smooth saturation curve: 1 signal/day -> ~0.22, 5 signals/day -> ~0.71, 20/day -> ~0.99
    return 1.0 - math.exp(-rate / 4.0)


def _compute_sources(signals: Sequence[SignalForMatching]) -> float:
    if not signals:
        return 0.0
    distinct = len({s.source_id for s in signals})
    # 1 source -> ~0.28, 3 sources -> ~0.63, 5 sources -> ~0.81, 10 sources -> ~0.96
    return 1.0 - math.exp(-distinct / 3.0)


def _compute_spread(signals: Sequence[SignalForMatching]) -> float:
    areas = {
        (loc.country_code, loc.admin1)
        for s in signals
        for loc in s.locations
        if loc.country_code is not None
    }
    if not areas:
        return 0.0
    distinct = len(areas)
    # 1 area -> ~0.39, 2 areas -> ~0.63, 4 areas -> ~0.86
    return 1.0 - math.exp(-distinct / 2.0)


def _compute_precision(signals: Sequence[SignalForMatching]) -> float:
    all_precisions = [precision_weight(loc.precision) for s in signals for loc in s.locations]
    if not all_precisions:
        return 0.0
    return sum(all_precisions) / len(all_precisions)


def early_signal_score(
    signals: Sequence[SignalForMatching],
    *,
    now: datetime | None = None,
    weights: Mapping[str, float] = DEFAULT_EARLY_SIGNAL_WEIGHTS,
) -> ScoreBreakdown:
    """Compute the early signal score in 0-1 for an event's signal set."""
    if not signals:
        return ScoreBreakdown(
            components={
                "recency": 0.0,
                "velocity": 0.0,
                "sources": 0.0,
                "spread": 0.0,
                "precision": 0.0,
            },
            total=0.0,
        )

    eval_now = now if now is not None else datetime.now(UTC)

    rec = _compute_recency(signals, eval_now)
    vel = _compute_velocity(signals)
    src = _compute_sources(signals)
    spr = _compute_spread(signals)
    prc = _compute_precision(signals)

    components = {
        "recency": rec,
        "velocity": vel,
        "sources": src,
        "spread": spr,
        "precision": prc,
    }

    w_rec = weights.get("recency", 0.25)
    w_vel = weights.get("velocity", 0.20)
    w_src = weights.get("sources", 0.25)
    w_spr = weights.get("spread", 0.15)
    w_prc = weights.get("precision", 0.15)

    total = w_rec * rec + w_vel * vel + w_src * src + w_spr * spr + w_prc * prc
    total_clamped = max(0.0, min(1.0, total))
    return ScoreBreakdown(components=components, total=total_clamped)
