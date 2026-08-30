"""Contracts crossing the clustering, matching, scoring, and storage seams.

Every model here is pure Pydantic v2: frozen, extra forbidden, zero database
or network imports.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from episignal_backend.ai.schema import BriefPoint, Extraction
from episignal_backend.db.types import CredibilityTier, LocationRole, Precision


class MatchAction(StrEnum):
    """The outcome of matching a cluster against candidate events.

    ``AMBIGUOUS`` is a single candidate scoring between the review and auto
    thresholds: the deterministic engine cannot decide, so an LLM judge must.
    """

    ATTACH = "attach"
    CREATE = "create"
    REFUSE = "refuse"
    AMBIGUOUS = "ambiguous"


class MatchRejection(StrEnum):
    """Why one candidate event could not accept a story cluster."""

    DISEASE_MISMATCH = "disease_mismatch"
    CONFLICTING_ADMIN1 = "conflicting_admin1"
    OUTSIDE_TIME_WINDOW = "outside_time_window"
    TOO_FAR = "too_far"
    SCORE_BELOW_THRESHOLD = "score_below_threshold"


class LocationForMatching(BaseModel):
    """A resolved location associated with a signal or event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    location_role: LocationRole
    precision: Precision
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    admin1: str | None = None
    admin2: str | None = None
    place_name: str | None = None
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)

    @model_validator(mode="after")
    def validate_coordinates(self) -> "LocationForMatching":
        if self.precision != Precision.UNRESOLVED and (
            self.latitude is None or self.longitude is None
        ):
            raise ValueError(
                f"Coordinates are required for precision {self.precision}; "
                "only unresolved locations may have null coordinates"
            )
        return self


class SignalForMatching(BaseModel):
    """A geocoded signal ready for story clustering and matching."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: UUID
    disease_id: UUID | None = None
    source_id: UUID
    source_is_official: bool
    credibility_tier: CredibilityTier
    published_at: datetime | None = None
    first_seen_at: datetime
    title: str = ""
    locations: tuple[LocationForMatching, ...] = ()
    extraction: Extraction | None = None
    embedding: tuple[float, ...] | None = None


_PRECISION_RANK = {
    Precision.PLACE: 4,
    Precision.ADMIN2: 3,
    Precision.ADMIN1: 2,
    Precision.COUNTRY: 1,
    Precision.UNRESOLVED: 0,
}


class StoryCluster(BaseModel):
    """A transient group of signals reporting the same outbreak."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signals: tuple[SignalForMatching, ...] = Field(min_length=1)

    @property
    def disease_id(self) -> UUID | None:
        return self.signals[0].disease_id

    @property
    def representative_location(self) -> LocationForMatching | None:
        """The highest-precision primary location in the cluster.

        Falls back to highest-precision location with any role if no primary exists.
        """
        all_locs = [loc for sig in self.signals for loc in sig.locations]
        if not all_locs:
            return None

        primary_locs = [loc for loc in all_locs if loc.location_role == LocationRole.PRIMARY]
        candidates = primary_locs if primary_locs else all_locs

        return max(candidates, key=lambda loc: _PRECISION_RANK.get(loc.precision, -1))

    @property
    def span(self) -> tuple[datetime, datetime]:
        """Earliest and latest signal timestamp across the cluster."""
        timestamps = [
            sig.published_at if sig.published_at is not None else sig.first_seen_at
            for sig in self.signals
        ]
        return min(timestamps), max(timestamps)

    @property
    def representative_embedding(self) -> tuple[float, ...] | None:
        """Use the first available member embedding, preserving cluster order."""
        return next(
            (signal.embedding for signal in self.signals if signal.embedding is not None),
            None,
        )


class CandidateEvent(BaseModel):
    """An existing event retrieved from storage as a candidate match."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID
    disease_id: UUID
    locations: tuple[LocationForMatching, ...] = ()
    first_signal_at: datetime
    last_updated_at: datetime
    representative_embedding: tuple[float, ...] | None = None
    title: str = ""
    recent_source_titles: tuple[str, ...] = ()


class MatchDecision(BaseModel):
    """The conservative matching decision for a story cluster."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: MatchAction
    event_id: UUID | None = None
    match_score: float | None = Field(default=None, ge=0.0, le=1.0)
    candidate_scores: dict[UUID, float] = Field(default_factory=dict)
    candidate_rejections: dict[UUID, MatchRejection | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_decision(self) -> "MatchDecision":
        # AMBIGUOUS carries exactly one candidate and its score, like ATTACH,
        # so the assembly knows which event the judge must consider.
        carries_target = self.action in (MatchAction.ATTACH, MatchAction.AMBIGUOUS)
        if carries_target:
            if self.event_id is None:
                raise ValueError(f"A {self.action} decision must carry an event_id")
            if self.match_score is None:
                raise ValueError(f"A {self.action} decision must carry a match_score")
        else:
            if self.event_id is not None:
                raise ValueError(f"A {self.action} decision must not carry an event_id")
            if self.match_score is not None:
                raise ValueError(f"A {self.action} decision must not carry a match_score")
        return self


class ScoreBreakdown(BaseModel):
    """The component breakdown and total for a calculated score."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    components: dict[str, float]
    total: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_components(self) -> "ScoreBreakdown":
        for name, value in self.components.items():
            if not (0.0 <= value <= 1.0):
                raise ValueError(f"Component '{name}' score {value} is out of bounds [0.0, 1.0]")
        return self


class SummarySource(BaseModel):
    """One source the summarizer may read, already in pick order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: UUID
    title: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    is_official: bool = False
    published_at: datetime | None = None
    brief: tuple[BriefPoint, ...] = ()


class EventForSummary(BaseModel):
    """Everything the summarizer needs to write one event's narrative."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID
    public_id: str = Field(min_length=1)
    disease: str = ""
    location: str = ""
    headline: str | None = None
    summary: str | None = None
    # The counts snapshot the last summary was written against, and the latest
    # observation today. Material-change detection compares the two.
    previous_counts: dict[str, object] | None = None
    latest_observation: dict[str, object] | None = None
    unsummarized_articles: int = 0
    last_summarized_at: datetime | None = None
    sources: tuple[SummarySource, ...] = ()
