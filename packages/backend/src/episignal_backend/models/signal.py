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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin, TimestampMixin
from episignal_backend.db.types import DiscoveryMethod, ProcessingStatus, SignalType, vocabulary


class Signal(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("url", "content_hash", name="uq_signals_url_content_hash"),
        CheckConstraint(
            "relevance_score >= 0 AND relevance_score <= 1", name="relevance_score_range"
        ),
        Index("ix_signals_source_id", "source_id"),
        Index("ix_signals_published_at", "published_at"),
        Index("ix_signals_canonical_url", "canonical_url"),
        Index("ix_signals_content_hash", "content_hash"),
        Index("ix_signals_processing_status", "processing_status"),
        Index("ix_signals_discovered_via", "discovered_via"),
        Index("ix_signals_first_seen_at", "first_seen_at"),
    )

    source_id: Mapped[UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    language: Mapped[str | None] = mapped_column(String(8))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
    discovered_via: Mapped[DiscoveryMethod] = mapped_column(
        vocabulary(DiscoveryMethod, "discovery_method_values"),
        nullable=False,
        default=DiscoveryMethod.DIRECT,
        server_default=DiscoveryMethod.DIRECT.value,
    )
    # Distinct from created_at: a revision is stored as a new row with a new
    # created_at, but first_seen_at must survive that or detection lead time
    # measures the revision rather than the discovery.
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    gdelt_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # timestamptz normalizes to UTC and discards the offset the publisher wrote,
    # which is a property of the document, not of the reader.
    published_at_offset_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    # Bounds the retry pass. A stub stops being selected once the budget is
    # spent, so the counter is also the reason a row stopped moving.
    retrieval_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    query_rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("gdelt_query_rules.id", ondelete="SET NULL")
    )

