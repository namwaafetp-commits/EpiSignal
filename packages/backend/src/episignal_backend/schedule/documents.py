"""Contracts across the scheduler's seams.

Pure data. This module imports neither SQLAlchemy nor httpx, so the ordering,
the failure policy, and the window arithmetic can be tested without a database,
a socket, or a model call.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class StageName(StrEnum):
    """One step of the pipeline. Never a rung of the model ladder: that is a tier."""

    INGEST_WHO = "ingest_who"
    INGEST_ECDC = "ingest_ecdc"
    DISCOVER = "discover"
    RETRIEVE = "retrieve"
    CLASSIFY = "classify"
    DEDUPE = "dedupe"
    TRIAGE = "triage"
    EMBED = "embed"
    PREGROUP = "pregroup"
    EXTRACT = "extract"
    GEOCODE = "geocode"
    MATCH = "match"
    SUMMARIZE = "summarize"


@dataclass(frozen=True)
class DiscoveryWindow:
    """The span of publication time a discovery pass asks GDELT for."""

    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        # run_discovery takes minutes, not instants. A window rounding to zero
        # would ask for nothing at all, so the floor is one minute.
        return max(1, int((self.end - self.start).total_seconds() // 60))


@dataclass
class PipelineCohort:
    """In-memory identity of the signals and events touched by one run."""

    signal_ids: tuple[UUID, ...] = ()
    touched_event_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True)
class StageOutcome:
    """What one stage did, or the type of the exception that stopped it."""

    stage: StageName
    ok: bool
    counts: Mapping[str, Any] = field(default_factory=dict)
    # The exception's type name only. Never its payload: an exception raised
    # near the session can carry the connection string.
    error: str | None = None
    duration_sec: float | None = None
    error_category: str | None = None


@dataclass(frozen=True)
class ChainOutcome:
    outcomes: tuple[StageOutcome, ...]

    @property
    def failed_stages(self) -> tuple[StageName, ...]:
        return tuple(outcome.stage for outcome in self.outcomes if not outcome.ok)

    @property
    def ok(self) -> bool:
        return not self.failed_stages
