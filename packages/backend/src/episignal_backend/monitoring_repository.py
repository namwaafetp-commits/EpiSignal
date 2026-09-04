"""Best-effort storage boundary for operational pipeline health telemetry."""

import logging
from dataclasses import fields
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from episignal_backend.db.session import session_scope
from episignal_backend.db.types import PipelineTrigger
from episignal_backend.models import PipelineHealthRun, PipelineRun
from episignal_backend.operational_monitoring import PipelineHealthRecord

logger = logging.getLogger(__name__)


class SqlAlchemyPipelineHealthRepository:
    """Persist and read health rows without touching core pipeline transactions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, record: PipelineHealthRecord) -> None:
        values = {
            field.name: getattr(record, field.name)
            for field in fields(PipelineHealthRecord)
            if field.name not in {"run_id", "trigger", "stage_durations_sec"}
        }
        values["pipeline_run_id"] = record.run_id
        self._session.merge(PipelineHealthRun(**values))

    def recent_records(
        self, now: datetime, *, lookback_days: int = 8
    ) -> tuple[PipelineHealthRecord, ...]:
        rows = self._session.execute(
            select(PipelineHealthRun, PipelineRun.trigger, PipelineRun.stage_counts)
            .join(PipelineRun, PipelineRun.id == PipelineHealthRun.pipeline_run_id)
            .where(
                PipelineHealthRun.finished_at.is_not(None),
                PipelineHealthRun.finished_at > now - timedelta(days=lookback_days),
                PipelineHealthRun.finished_at <= now,
            )
            .order_by(PipelineHealthRun.finished_at.desc())
        ).all()
        return tuple(
            self._record_from_row(health_row, trigger, stage_counts)
            for health_row, trigger, stage_counts in rows
        )

    @staticmethod
    def _record_from_row(
        row: PipelineHealthRun,
        trigger: PipelineTrigger,
        stage_counts: Any,
    ) -> PipelineHealthRecord:
        return PipelineHealthRecord(
            run_id=row.pipeline_run_id,
            started_at=row.started_at,
            finished_at=row.finished_at,
            status=row.status,
            trigger=trigger,
            duration_sec=row.duration_sec,
            stage_durations_sec=_stage_durations(stage_counts),
            discovered=row.discovered,
            dedup_primary=row.dedup_primary,
            deepseek_requested=row.deepseek_requested,
            deepseek_success=row.deepseek_success,
            deepseek_relevant=row.deepseek_relevant,
            retrieval_requested=row.retrieval_requested,
            retrieval_success=row.retrieval_success,
            gemini_requested=row.gemini_requested,
            gemini_success=row.gemini_success,
            grouping_requested=row.grouping_requested,
            grouping_success=row.grouping_success,
            mistral_requested=row.mistral_requested,
            mistral_success=row.mistral_success,
            new_events=row.new_events,
            updated_events=row.updated_events,
            summarized_events=row.summarized_events,
            fatal_error_count=row.fatal_error_count,
            error_categories=row.error_categories,
            unknown_disease_rate=row.unknown_disease_rate,
            no_location_rate=row.no_location_rate,
            new_event_rate=row.new_event_rate,
            matched_existing_event_rate=row.matched_existing_event_rate,
            duplicate_article_rate=row.duplicate_article_rate,
            average_signals_per_event=row.average_signals_per_event,
            dashboard_response_ms=row.dashboard_response_ms,
            endpoint_latency_ms=row.endpoint_latency_ms,
            db_query_duration_ms=row.db_query_duration_ms,
            unavailable_metrics=row.unavailable_metrics,
        )


def _stage_durations(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    durations: dict[str, float] = {}
    for stage, counts in raw.items():
        if not isinstance(stage, str) or not isinstance(counts, dict):
            continue
        duration = counts.get("duration_sec")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0:
            durations[stage] = float(duration)
    return durations


def persist_pipeline_health_best_effort(record: PipelineHealthRecord) -> None:
    """Write telemetry in its own transaction; never raise into the pipeline."""
    try:
        with session_scope() as session:
            SqlAlchemyPipelineHealthRepository(session).record(record)
    except Exception as error:
        logger.warning("Pipeline health persistence unavailable (%s)", type(error).__name__)
