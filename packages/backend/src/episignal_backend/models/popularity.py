from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin


class EventPopularityMetric(IdentityMixin, Base):
    """Aggregate-only Briefing popularity for one rolling analytics window."""

    __tablename__ = "event_popularity_metrics"
    __table_args__ = (
        CheckConstraint(
            "impressions_unique >= 0 AND briefing_opens_unique >= 0",
            name="non_negative_counts",
        ),
        CheckConstraint(
            "baseline_ctr >= 0 AND baseline_ctr <= 1",
            name="baseline_ctr_range",
        ),
        CheckConstraint(
            "smoothed_ctr >= 0 AND smoothed_ctr <= 1",
            name="smoothed_ctr_range",
        ),
        CheckConstraint(
            "engagement_score >= 0 AND engagement_score <= 1",
            name="engagement_score_range",
        ),
        UniqueConstraint(
            "event_id",
            "window_start",
            "window_end",
            name="uq_event_popularity_metrics_event_window",
        ),
        Index("ix_event_popularity_metrics_event", "event_id"),
        Index(
            "ix_event_popularity_metrics_event_window_end",
            "event_id",
            "window_end",
        ),
    )

    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    impressions_unique: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    briefing_opens_unique: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    baseline_ctr: Mapped[float | None] = mapped_column(Float)
    smoothed_ctr: Mapped[float | None] = mapped_column(Float)
    engagement_score: Mapped[float | None] = mapped_column(Float)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
