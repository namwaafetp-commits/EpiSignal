"""Pure pipeline health telemetry and deterministic operational evaluation."""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from statistics import mean
from uuid import UUID
from zoneinfo import ZoneInfo

from episignal_backend.db.types import PipelineRunStatus
from episignal_backend.schedule.documents import ChainOutcome, StageName

BANGKOK = ZoneInfo("Asia/Bangkok")
SCHEDULE_INTERVAL_MINUTES = 60
EXPECTED_RUNS_PER_DAY = 1440 // SCHEDULE_INTERVAL_MINUTES
HEALTHY_COVERAGE = 0.98
WARNING_COVERAGE = 0.95
HEALTHY_SUCCESS = 0.99
WARNING_SUCCESS = 0.95
STAGE_TARGETS = {
    "deepseek": 0.99,
    "retrieval": 0.95,
    "gemini": 0.98,
    "grouping": 0.99,
    "mistral": 0.98,
}


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    NEUTRAL = "neutral"


class VolumeAnomaly(StrEnum):
    NORMAL = "normal"
    LOW = "low"
    HIGH = "high"
    INSUFFICIENT_DATA = "insufficient_data"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class HealthMetric:
    value: float | None
    status: HealthStatus


@dataclass(frozen=True)
class PipelineHealthRecord:
    run_id: UUID
    started_at: datetime
    finished_at: datetime | None
    status: PipelineRunStatus
    duration_sec: float | None = None
    discovered: int | None = None
    dedup_primary: int | None = None
    deepseek_requested: int | None = None
    deepseek_success: int | None = None
    deepseek_relevant: int | None = None
    retrieval_requested: int | None = None
    retrieval_success: int | None = None
    gemini_requested: int | None = None
    gemini_success: int | None = None
    grouping_requested: int | None = None
    grouping_success: int | None = None
    mistral_requested: int | None = None
    mistral_success: int | None = None
    new_events: int | None = None
    updated_events: int | None = None
    summarized_events: int | None = None
    fatal_error_count: int | None = None
    error_categories: Mapping[str, int] = field(default_factory=dict)
    unknown_disease_rate: float | None = None
    no_location_rate: float | None = None
    new_event_rate: float | None = None
    matched_existing_event_rate: float | None = None
    duplicate_article_rate: float | None = None
    average_signals_per_event: float | None = None
    dashboard_response_ms: float | None = None
    endpoint_latency_ms: float | None = None
    db_query_duration_ms: float | None = None
    unavailable_metrics: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthSummary:
    status: HealthStatus
    expected_runs: int
    current_day_expected_runs_so_far: int
    completed_runs: int
    run_coverage: float | None
    coverage_status: HealthStatus
    successful_runs: int
    success_rate: float | None
    success_status: HealthStatus
    latest_run: datetime | None
    freshness_minutes: float | None
    freshness_status: HealthStatus
    p95_runtime_sec: float | None
    runtime_status: HealthStatus
    fatal_errors: int | None
    fatal_error_status: HealthStatus
    stage_success_rates: Mapping[str, HealthMetric]
    discovered: int | None
    relevant: int | None
    new_events: int | None
    updated_events: int | None
    summarized_events: int | None
    baseline_discovered_per_day: float | None
    baseline_status: HealthStatus
    volume_anomaly: VolumeAnomaly
    quality_watch: Mapping[str, HealthMetric]
    unavailable_metrics: Mapping[str, str]


def _stage_counts(outcome: ChainOutcome, stage: StageName) -> Mapping[str, int] | None:
    for item in outcome.outcomes:
        if item.stage is stage:
            return item.counts if item.ok else None
    return None


def _count(counts: Mapping[str, int] | None, key: str) -> int | None:
    value = counts.get(key) if counts is not None else None
    return value if isinstance(value, int) else None


def _sum_counts(counts: Mapping[str, int] | None, keys: Sequence[str]) -> int | None:
    if counts is None or not all(key in counts for key in keys):
        return None
    values = [counts[key] for key in keys]
    return sum(value for value in values if isinstance(value, int))


def _rate(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def build_health_record(
    *,
    run_id: UUID,
    started_at: datetime,
    finished_at: datetime | None,
    outcome: ChainOutcome,
    fatal_error_type: str | None = None,
) -> PipelineHealthRecord:
    """Translate existing stage outputs into optional monitoring telemetry."""
    discover = _stage_counts(outcome, StageName.DISCOVER)
    dedupe = _stage_counts(outcome, StageName.DEDUPE)
    deepseek = _stage_counts(outcome, StageName.CLASSIFY)
    retrieval = _stage_counts(outcome, StageName.RETRIEVE)
    gemini = _stage_counts(outcome, StageName.EXTRACT)
    grouping = _stage_counts(outcome, StageName.MATCH)
    mistral = _stage_counts(outcome, StageName.SUMMARIZE)

    deepseek_success = _sum_counts(deepseek, ("relevant", "irrelevant"))
    retrieval_success = _sum_counts(retrieval, ("retrieved", "filtered", "duplicates", "redundant"))
    grouping_success = _count(grouping, "attached")
    mistral_requested = _sum_counts(mistral, ("summarized", "failed", "unavailable"))

    new_events = _count(grouping, "created")
    updated_events = _count(grouping, "updated")
    event_total = None
    if new_events is not None and updated_events is not None:
        event_total = new_events + updated_events

    errors = Counter(item.error or "unknown" for item in outcome.outcomes if not item.ok)
    if fatal_error_type is not None:
        errors[fatal_error_type] += 1
    fatal_error_count = len(outcome.failed_stages) + (1 if fatal_error_type else 0)

    unavailable = {
        "unknown_disease_rate": "stage outputs do not expose per-signal disease resolution",
        "no_location_rate": "stage outputs do not expose per-signal location resolution",
        "average_signals_per_event": "grouping output does not expose attached-signal cardinality",
        "dashboard_response_ms": "dashboard/API latency is not instrumented in Phase 1",
        "endpoint_latency_ms": "endpoint latency is not instrumented in Phase 1",
        "db_query_duration_ms": "database query timing is not instrumented in Phase 1",
    }

    return PipelineHealthRecord(
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        status=(
            PipelineRunStatus.FAILED
            if not outcome.ok or fatal_error_type is not None
            else PipelineRunStatus.SUCCEEDED
        ),
        duration_sec=(finished_at - started_at).total_seconds() if finished_at else None,
        discovered=_count(discover, "discovered"),
        dedup_primary=_count(dedupe, "primaries"),
        deepseek_requested=_count(deepseek, "requests"),
        deepseek_success=deepseek_success,
        deepseek_relevant=_count(deepseek, "relevant"),
        retrieval_requested=_count(retrieval, "examined"),
        retrieval_success=retrieval_success,
        gemini_requested=_count(gemini, "requests"),
        gemini_success=_count(gemini, "extracted"),
        grouping_requested=_count(grouping, "seen"),
        grouping_success=grouping_success,
        mistral_requested=mistral_requested,
        mistral_success=_count(mistral, "summarized"),
        new_events=new_events,
        updated_events=updated_events,
        summarized_events=_count(mistral, "summarized"),
        fatal_error_count=fatal_error_count,
        error_categories=dict(errors),
        new_event_rate=_rate(new_events, event_total),
        matched_existing_event_rate=_rate(updated_events, event_total),
        duplicate_article_rate=_rate(
            _count(dedupe, "duplicates"),
            _sum_counts(dedupe, ("primaries", "duplicates")),
        ),
        unavailable_metrics=unavailable,
    )


def expected_runs_so_far(now: datetime, *, timezone: ZoneInfo = BANGKOK) -> int:
    """Count hourly schedule slots elapsed in the local calendar day."""
    local_now = now.astimezone(timezone)
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_minutes = max(0.0, (local_now - day_start).total_seconds() / 60)
    return min(
        EXPECTED_RUNS_PER_DAY,
        int(elapsed_minutes // SCHEDULE_INTERVAL_MINUTES) + 1,
    )


def _status_from_rate(
    rate: float | None,
    *,
    healthy_at: float,
    warning_at: float,
) -> HealthStatus:
    if rate is None:
        return HealthStatus.NEUTRAL
    if rate >= healthy_at:
        return HealthStatus.HEALTHY
    if rate >= warning_at:
        return HealthStatus.WARNING
    return HealthStatus.CRITICAL


def _coverage_status(coverage: float | None) -> HealthStatus:
    return _status_from_rate(
        coverage,
        healthy_at=HEALTHY_COVERAGE,
        warning_at=WARNING_COVERAGE,
    )


def _freshness_status(minutes: float | None) -> HealthStatus:
    if minutes is None:
        return HealthStatus.CRITICAL
    if minutes < 30:
        return HealthStatus.HEALTHY
    if minutes <= 60:
        return HealthStatus.WARNING
    return HealthStatus.CRITICAL


def _runtime_status(seconds: float | None) -> HealthStatus:
    if seconds is None:
        return HealthStatus.NEUTRAL
    if seconds < 900:
        return HealthStatus.HEALTHY
    if seconds <= 1800:
        return HealthStatus.WARNING
    return HealthStatus.CRITICAL


def _fatal_status(errors: int | None) -> HealthStatus:
    if errors is None:
        return HealthStatus.NEUTRAL
    if errors == 0:
        return HealthStatus.HEALTHY
    if errors == 1:
        return HealthStatus.WARNING
    return HealthStatus.CRITICAL


def _stage_metric(requested: int | None, success: int | None, target: float) -> HealthMetric:
    rate = _rate(success, requested)
    return HealthMetric(
        value=rate,
        status=_status_from_rate(rate, healthy_at=target, warning_at=WARNING_SUCCESS),
    )


def _p95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * 0.95
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _optional_sum(records: Sequence[PipelineHealthRecord], field_name: str) -> int | None:
    values = [getattr(record, field_name) for record in records]
    known = [value for value in values if isinstance(value, int)]
    return sum(known) if known else None


def _optional_mean(records: Sequence[PipelineHealthRecord], field_name: str) -> float | None:
    values = [getattr(record, field_name) for record in records]
    known = [value for value in values if isinstance(value, (int, float))]
    return mean(known) if known else None


def _severity(statuses: Sequence[HealthStatus]) -> HealthStatus:
    if HealthStatus.CRITICAL in statuses:
        return HealthStatus.CRITICAL
    if HealthStatus.WARNING in statuses:
        return HealthStatus.WARNING
    if HealthStatus.HEALTHY in statuses:
        return HealthStatus.HEALTHY
    return HealthStatus.NEUTRAL


def _baseline(
    records: Sequence[PipelineHealthRecord],
    *,
    now: datetime,
) -> tuple[float | None, HealthStatus, VolumeAnomaly]:
    today = now.astimezone(BANGKOK).date()
    daily: defaultdict[date, int] = defaultdict(int)
    for record in records:
        if record.finished_at is None or record.discovered is None:
            continue
        local_date = record.finished_at.astimezone(BANGKOK).date()
        if today - timedelta(days=7) <= local_date < today:
            daily[local_date] += record.discovered
    if len(daily) < 7:
        return None, HealthStatus.NEUTRAL, VolumeAnomaly.INSUFFICIENT_DATA

    baseline = mean(daily.values())
    current_records = [
        record
        for record in records
        if record.finished_at is not None and now - timedelta(hours=24) < record.finished_at <= now
    ]
    current_volume = _optional_sum(current_records, "discovered")
    if current_volume is None or baseline == 0:
        return baseline, HealthStatus.NEUTRAL, VolumeAnomaly.UNAVAILABLE
    if current_volume < baseline * 0.5:
        anomaly = VolumeAnomaly.LOW
    elif current_volume > baseline * 2:
        anomaly = VolumeAnomaly.HIGH
    else:
        anomaly = VolumeAnomaly.NORMAL
    return baseline, HealthStatus.NEUTRAL, anomaly


def summarize_health(
    records: Sequence[PipelineHealthRecord],
    *,
    now: datetime,
    expected_runs: int = EXPECTED_RUNS_PER_DAY,
    coverage_override: float | None = None,
) -> HealthSummary:
    """Evaluate completed health records from the preceding 24 hours."""
    window_start = now - timedelta(hours=24)
    completed = tuple(
        record
        for record in records
        if record.finished_at is not None and window_start < record.finished_at <= now
    )
    successful = sum(record.status is PipelineRunStatus.SUCCEEDED for record in completed)
    coverage = (
        coverage_override
        if coverage_override is not None
        else (len(completed) / expected_runs if expected_runs else None)
    )
    success_rate = _rate(successful, len(completed))
    finished_times = [record.finished_at for record in completed if record.finished_at is not None]
    latest = max(finished_times, default=None)
    freshness = (now - latest).total_seconds() / 60 if latest is not None else None
    runtime_values = [
        record.duration_sec for record in completed if record.duration_sec is not None
    ]
    fatal_errors = _optional_sum(completed, "fatal_error_count")

    stage_metrics = {
        "deepseek": _stage_metric(
            _optional_sum(completed, "deepseek_requested"),
            _optional_sum(completed, "deepseek_success"),
            STAGE_TARGETS["deepseek"],
        ),
        "retrieval": _stage_metric(
            _optional_sum(completed, "retrieval_requested"),
            _optional_sum(completed, "retrieval_success"),
            STAGE_TARGETS["retrieval"],
        ),
        "gemini": _stage_metric(
            _optional_sum(completed, "gemini_requested"),
            _optional_sum(completed, "gemini_success"),
            STAGE_TARGETS["gemini"],
        ),
        "grouping": _stage_metric(
            _optional_sum(completed, "grouping_requested"),
            _optional_sum(completed, "grouping_success"),
            STAGE_TARGETS["grouping"],
        ),
        "mistral": _stage_metric(
            _optional_sum(completed, "mistral_requested"),
            _optional_sum(completed, "mistral_success"),
            STAGE_TARGETS["mistral"],
        ),
    }
    baseline, baseline_status, volume_anomaly = _baseline(records, now=now)
    unavailable: dict[str, str] = {}
    for record in records:
        unavailable.update(record.unavailable_metrics)

    statuses = [
        _coverage_status(coverage),
        _status_from_rate(success_rate, healthy_at=HEALTHY_SUCCESS, warning_at=WARNING_SUCCESS),
        _freshness_status(freshness),
        _runtime_status(_p95(runtime_values)),
        _fatal_status(fatal_errors),
        *(metric.status for metric in stage_metrics.values()),
    ]
    quality = {
        "unknown_disease_rate": HealthMetric(
            _optional_mean(completed, "unknown_disease_rate"), HealthStatus.NEUTRAL
        ),
        "no_location_rate": HealthMetric(
            _optional_mean(completed, "no_location_rate"), HealthStatus.NEUTRAL
        ),
        "new_event_rate": HealthMetric(
            _optional_mean(completed, "new_event_rate"), HealthStatus.NEUTRAL
        ),
        "matched_existing_event_rate": HealthMetric(
            _optional_mean(completed, "matched_existing_event_rate"), HealthStatus.NEUTRAL
        ),
        "duplicate_article_rate": HealthMetric(
            _optional_mean(completed, "duplicate_article_rate"), HealthStatus.NEUTRAL
        ),
        "average_signals_per_event": HealthMetric(
            _optional_mean(completed, "average_signals_per_event"), HealthStatus.NEUTRAL
        ),
    }
    return HealthSummary(
        status=_severity(statuses),
        expected_runs=expected_runs,
        current_day_expected_runs_so_far=expected_runs_so_far(now),
        completed_runs=len(completed),
        run_coverage=coverage,
        coverage_status=_coverage_status(coverage),
        successful_runs=successful,
        success_rate=success_rate,
        success_status=_status_from_rate(
            success_rate, healthy_at=HEALTHY_SUCCESS, warning_at=WARNING_SUCCESS
        ),
        latest_run=latest,
        freshness_minutes=freshness,
        freshness_status=_freshness_status(freshness),
        p95_runtime_sec=_p95(runtime_values),
        runtime_status=_runtime_status(_p95(runtime_values)),
        fatal_errors=fatal_errors,
        fatal_error_status=_fatal_status(fatal_errors),
        stage_success_rates=stage_metrics,
        discovered=_optional_sum(completed, "discovered"),
        relevant=_optional_sum(completed, "deepseek_relevant"),
        new_events=_optional_sum(completed, "new_events"),
        updated_events=_optional_sum(completed, "updated_events"),
        summarized_events=_optional_sum(completed, "summarized_events"),
        baseline_discovered_per_day=baseline,
        baseline_status=baseline_status,
        volume_anomaly=volume_anomaly,
        quality_watch=quality,
        unavailable_metrics=unavailable,
    )
