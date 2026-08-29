"""Durable manual review cases and candidate snapshots.

A review case records one review episode for a signal where automation
refused to continue. Candidate snapshots preserve the exact qualifying
events and match scores at refusal time.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin, TimestampMixin
from episignal_backend.db.types import (
    ReviewReason,
    ReviewResolution,
    ReviewStatus,
    vocabulary,
)


class SignalReviewCase(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "signal_review_cases"
    __table_args__ = (
        CheckConstraint(
            "(status = 'open' AND resolution IS NULL AND resolved_at IS NULL) OR "
            "(status = 'resolved' AND resolution IS NOT NULL AND resolved_at IS NOT NULL)",
            name="review_resolution_state",
        ),
        CheckConstraint(
            "(resolution != 'assign_disease' AND selected_disease_id IS NULL) OR "
            "(resolution = 'assign_disease' AND selected_disease_id IS NOT NULL)",
            name="review_assign_disease_target",
        ),
        CheckConstraint(
            "(resolution NOT IN ('link_event', 'create_event') AND selected_event_id IS NULL) OR "
            "(resolution IN ('link_event', 'create_event') AND selected_event_id IS NOT NULL)",
            name="review_event_target",
        ),
        Index(
            "uq_signal_review_cases_one_open",
            "signal_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_signal_review_cases_queue", "status", "opened_at", "id"),
    )

    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[ReviewReason] = mapped_column(
        vocabulary(ReviewReason, "review_reason_values"), nullable=False
    )
    status: Mapped[ReviewStatus] = mapped_column(
        vocabulary(ReviewStatus, "review_status_values"), nullable=False
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[ReviewResolution | None] = mapped_column(
        vocabulary(ReviewResolution, "review_resolution_values")
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(String(1000))
    selected_disease_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("diseases.id", ondelete="RESTRICT")
    )
    selected_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT")
    )


class SignalReviewCandidate(Base):
    __tablename__ = "signal_review_candidates"
    __table_args__ = (
        CheckConstraint("match_score >= 0 AND match_score <= 1", name="match_score_range"),
    )
    review_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("signal_review_cases.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("events.id", ondelete="RESTRICT"), primary_key=True
    )
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
