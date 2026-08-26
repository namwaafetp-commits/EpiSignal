from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin, TimestampMixin
from episignal_backend.db.types import ProcessingStatus, SignalType, vocabulary


class Signal(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "signals"
    __table_args__ = (
        CheckConstraint(
            "relevance_score >= 0 AND relevance_score <= 1", name="relevance_score_range"
        ),
        Index("ix_signals_source_id", "source_id"),
        Index("ix_signals_published_at", "published_at"),
        Index("ix_signals_canonical_url", "canonical_url"),
        Index("ix_signals_content_hash", "content_hash"),
        Index("ix_signals_processing_status", "processing_status"),
    )

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    language: Mapped[str | None] = mapped_column(String(8))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    relevance_score: Mapped[float | None] = mapped_column(Float)
    public_health_relevant: Mapped[bool | None] = mapped_column(Boolean)
    signal_type: Mapped[SignalType] = mapped_column(
        vocabulary(SignalType, "signal_type_values"),
        nullable=False,
        default=SignalType.UNKNOWN,
    )
    ai_extraction: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ai_model: Mapped[str | None] = mapped_column(Text)
    ai_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        vocabulary(ProcessingStatus, "processing_status_values"),
        nullable=False,
        default=ProcessingStatus.FETCHED,
    )
