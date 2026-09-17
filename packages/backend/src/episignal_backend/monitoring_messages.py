"""Deterministic Telegram text for an evaluated pipeline health summary."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from episignal_backend.operational_monitoring import (
    BANGKOK,
    HEALTHY_COVERAGE,
    HEALTHY_FATAL_ERRORS,
    HEALTHY_FRESHNESS_MINUTES,
    HEALTHY_RUNTIME_SECONDS,
    HEALTHY_SUCCESS,
    STAGE_TARGETS,
    HealthMetric,
    HealthStatus,
    HealthSummary,
)

_MAX_TELEGRAM_UTF16_UNITS = 4095
_SAFE_FAILURE_CATEGORIES = {
    "connect_timeout",
    "read_timeout",
    "timeout",
    "dns_connect_error",
    "http_403",
    "http_429",
    "http_5xx",
    "http_other",
    "provider_unavailable",
    "malformed_response",
    "schema_parse_error",
    "blocked_robots",
    "invalid_content",
    "parser_failure",
    "storage_failure",
    "other",
}
_SAFE_DOMAIN = re.compile(
    r"(?i)^(?=.{1,120}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)

_STATUS_ICONS = {
    HealthStatus.HEALTHY: "🟢",
    HealthStatus.WARNING: "🟡",
    HealthStatus.CRITICAL: "🔴",
    HealthStatus.NEUTRAL: "⚪",
}
_STAGE_LABELS = {
    "deepseek": "DeepSeek",
    "retrieval": "Retrieval",
    "gemini": "Gemini",
    "grouping": "Grouping",
    "mistral": "Mistral",
}
_ENGLISH_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


def format_daily_report(summary: HealthSummary, *, now: datetime) -> str:
    """Render the evaluator's current health result without re-evaluating it."""
    local_now = now.astimezone(BANGKOK)
    pipeline = [
        "Pipeline (coverage: current ICT day; output and runs: trailing 24h)",
        _line(summary.coverage_status, "Coverage", _coverage(summary)),
        _line(
            summary.success_status,
            "Run success",
            _ratio(summary.successful_runs, summary.completed_runs, summary.success_rate),
        ),
        _line(summary.freshness_status, "Freshness", _minutes(summary.freshness_minutes)),
        _line(summary.runtime_status, "p95 runtime", _seconds(summary.p95_runtime_sec)),
        _line(summary.fatal_error_status, "Fatal errors", _number(summary.fatal_errors)),
    ]
    if summary.latest_run is not None:
        latest = summary.latest_run.astimezone(BANGKOK)
        pipeline.append(f"✓ Last completed run: {_bangkok_timestamp(latest)}")

    stages = ["Stages"]
    for name, label in _STAGE_LABELS.items():
        metric = _stage_metric(summary, name)
        stages.append(
            _line(
                metric.status,
                label,
                f"{_percent(metric.value)} (healthy ≥{_percent(STAGE_TARGETS[name])})",
            )
        )

    output = [
        "24h Output",
        f"Discovered: {_number(summary.discovered)}",
        f"Relevant: {_number(summary.relevant)}",
        f"New events: {_number(summary.new_events)}",
        f"Updated events: {_number(summary.updated_events)}",
        f"Summarized events: {_number(summary.summarized_events)}",
    ]
    failures = ["Recent failures", *_format_recent_failures(summary)]
    overall = f"Overall: {summary.status.value.upper()}"
    return _telegram_text(
        "\n\n".join(
            (
                f"{_STATUS_ICONS[summary.status]} EpiSignal Daily Health\n"
                f"{_bangkok_date(local_now)} (ICT)",
                "\n".join(pipeline),
                "\n".join(stages),
                "\n".join(output),
                "\n".join(failures),
                overall,
            )
        )
    )


def format_abnormal_alert(summary: HealthSummary, *, now: datetime) -> str:
    """Render an evaluated WARNING or CRITICAL state without diagnosing it."""
    local_now = now.astimezone(BANGKOK)
    abnormal = [
        _line(metric.status, metric.label, f"{metric.value} ({metric.threshold})")
        for metric in abnormal_metrics(summary)
    ]
    stages = ["Stages"]
    for name, label in _STAGE_LABELS.items():
        metric = _stage_metric(summary, name)
        stages.append(
            _line(
                metric.status,
                label,
                f"{_percent(metric.value)} (healthy ≥{_percent(STAGE_TARGETS[name])})",
            )
        )
    context = [
        "Context",
        _line(summary.coverage_status, "Coverage", _coverage(summary)),
        _line(
            summary.success_status,
            "Run success",
            _ratio(summary.successful_runs, summary.completed_runs, summary.success_rate),
        ),
        _line(summary.freshness_status, "Freshness", _minutes(summary.freshness_minutes)),
    ]
    if summary.latest_run is not None:
        latest = summary.latest_run.astimezone(BANGKOK)
        context.append(f"✓ Last completed run: {_bangkok_timestamp(latest)}")
    return _telegram_text(
        "\n\n".join(
            (
                f"{_STATUS_ICONS[summary.status]} EpiSignal {summary.status.value.upper()}\n"
                f"{_bangkok_timestamp(local_now)}",
                "\n".join(("Abnormal metrics", *abnormal))
                if abnormal
                else "Abnormal metrics\nNone",
                "\n".join(stages),
                "\n".join(context),
                "\n".join(("Recent failures", *_format_recent_failures(summary))),
            )
        )
    )


def format_recovery(summary: HealthSummary, *, previous_status: HealthStatus, now: datetime) -> str:
    """Render a deterministic return to a healthy evaluator status."""
    local_now = now.astimezone(BANGKOK)
    run_success = _ratio(summary.successful_runs, summary.completed_runs, summary.success_rate)
    return _telegram_text(
        "\n\n".join(
            (
                "\n".join(
                    (
                        "🟢 EpiSignal RECOVERED",
                        f"Previous status: {previous_status.value.upper()}",
                        f"Current status: {summary.status.value.upper()}",
                    )
                ),
                "\n".join(
                    (
                        f"Coverage: {_coverage(summary)}",
                        f"Run success: {run_success}",
                        f"Freshness: {_minutes(summary.freshness_minutes)}",
                    )
                ),
                f"Recovered: {_bangkok_timestamp(local_now)}",
            )
        )
    )


def abnormal_fingerprint(summary: HealthSummary) -> str:
    """Identify an abnormal evaluator state without including volatile values."""
    identities = sorted(
        f"{metric.identity}:{metric.status.value}" for metric in abnormal_metrics(summary)
    )
    return "|".join((summary.status.value, *identities))


@dataclass(frozen=True)
class AbnormalMetric:
    """A display-only view of one non-healthy evaluator metric."""

    identity: str
    label: str
    value: str
    threshold: str
    status: HealthStatus


def abnormal_metrics(summary: HealthSummary) -> tuple[AbnormalMetric, ...]:
    """Return only statuses already marked abnormal by the health evaluator."""
    pipeline = (
        (
            "coverage",
            "Coverage",
            _coverage(summary),
            f"healthy ≥{_percent(HEALTHY_COVERAGE)}",
            summary.coverage_status,
        ),
        (
            "run_success",
            "Run success",
            _ratio(summary.successful_runs, summary.completed_runs, summary.success_rate),
            f"healthy ≥{_percent(HEALTHY_SUCCESS)}",
            summary.success_status,
        ),
        (
            "freshness",
            "Freshness",
            _minutes(summary.freshness_minutes),
            f"healthy <{_minutes(HEALTHY_FRESHNESS_MINUTES)}",
            summary.freshness_status,
        ),
        (
            "p95_runtime",
            "p95 runtime",
            _seconds(summary.p95_runtime_sec),
            f"healthy <{_seconds(HEALTHY_RUNTIME_SECONDS)}",
            summary.runtime_status,
        ),
        (
            "fatal_errors",
            "Fatal errors",
            _number(summary.fatal_errors),
            f"healthy {HEALTHY_FATAL_ERRORS}",
            summary.fatal_error_status,
        ),
    )
    stages = tuple(
        (
            f"stage:{name}",
            label,
            _percent(metric.value),
            f"healthy ≥{_percent(STAGE_TARGETS[name])}",
            metric.status,
        )
        for name, label in _STAGE_LABELS.items()
        if (metric := summary.stage_success_rates.get(name)) is not None
        and metric.status in {HealthStatus.WARNING, HealthStatus.CRITICAL}
    )
    metrics = pipeline + stages
    return tuple(
        AbnormalMetric(identity, label, value, threshold, status)
        for identity, label, value, threshold, status in metrics
        if status in {HealthStatus.WARNING, HealthStatus.CRITICAL}
    )


def _line(status: HealthStatus, label: str, value: str) -> str:
    return f"{_marker(status)} {label}: {value}"


def _marker(status: HealthStatus) -> str:
    return "✓" if status in {HealthStatus.HEALTHY, HealthStatus.NEUTRAL} else _STATUS_ICONS[status]


def _coverage(summary: HealthSummary) -> str:
    if summary.run_coverage is None:
        return "N/A"
    return (
        f"{_percent(summary.run_coverage)} "
        f"({summary.current_day_expected_runs_so_far} scheduled slots due today)"
    )


def _ratio(successful: int, completed: int, rate: float | None) -> str:
    if rate is None:
        return "N/A"
    return f"{successful}/{completed} ({_percent(rate)})"


def _percent(value: float | None) -> str:
    if value is None:
        return "N/A"
    percentage = float(value) * 100
    return f"{percentage:.0f}%" if percentage.is_integer() else f"{percentage:.1f}%"


def _stage_metric(summary: HealthSummary, name: str) -> HealthMetric:
    return summary.stage_success_rates.get(name, HealthMetric(None, HealthStatus.NEUTRAL))


def _bangkok_date(value: datetime) -> str:
    return f"{value.day} {_ENGLISH_MONTHS[value.month - 1]} {value.year}"


def _bangkok_timestamp(value: datetime) -> str:
    return f"{_bangkok_date(value)} {value.hour:02d}:{value.minute:02d} ICT"


def _minutes(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.0f}m"


def _seconds(value: float | None) -> str:
    if value is None:
        return "N/A"
    minutes, seconds = divmod(round(value), 60)
    return f"{minutes}m" if seconds == 0 else f"{minutes}m {seconds}s"


def _number(value: int | None) -> str:
    return "N/A" if value is None else str(value)


def _format_recent_failures(summary: HealthSummary) -> list[str]:
    lines: list[str] = []
    for stage, label in (("retrieval", "Retrieval"), ("mistral", "Mistral")):
        items = summary.recent_failures.get(stage, ())
        for item in items[:5]:
            if isinstance(item, Mapping):
                lines.append(f"- {label}: {_safe_failure_detail(item)}")
            if len(lines) == 8:
                return lines
    return lines or ["None"]


def _safe_failure_detail(item: Mapping[str, Any]) -> str:
    category = item.get("category")
    safe_category = (
        category if isinstance(category, str) and category in _SAFE_FAILURE_CATEGORIES else None
    )
    status = _safe_http_status(item.get("http_status")) or _safe_http_status(
        item.get("status_code")
    )
    status_class = item.get("provider_status_class")
    safe_status_class = (
        status_class
        if isinstance(status_class, str) and re.fullmatch(r"[45]xx", status_class)
        else None
    )
    detail = _category_label(safe_category)
    if status is not None:
        detail = f"HTTP {status}"
    elif safe_status_class is not None:
        detail = f"{detail} (HTTP {safe_status_class})"
    domain = item.get("domain")
    if isinstance(domain, str) and _SAFE_DOMAIN.fullmatch(domain):
        return f"{domain.lower()} — {detail}"
    return detail


def _safe_http_status(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 400 <= value <= 599:
        return value
    return None


def _category_label(category: str | None) -> str:
    return category.replace("_", " ") if category is not None else "failure"


def _telegram_text(text: str) -> str:
    """Keep a message strictly below Telegram's UTF-16 message limit."""
    if _utf16_units(text) <= _MAX_TELEGRAM_UTF16_UNITS:
        return text
    suffix = "\n…"
    limit = _MAX_TELEGRAM_UTF16_UNITS - _utf16_units(suffix)
    used = 0
    kept: list[str] = []
    for character in text:
        character_units = _utf16_units(character)
        if used + character_units > limit:
            break
        kept.append(character)
        used += character_units
    return "".join(kept) + suffix


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2
