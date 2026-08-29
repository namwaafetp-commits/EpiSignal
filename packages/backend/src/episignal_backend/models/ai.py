from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin, TimestampMixin
from episignal_backend.db.types import AiOutcome, AiProvider, AiPurpose, vocabulary

PRICE = Numeric(12, 6)


class AiModel(IdentityMixin, TimestampMixin, Base):
    """One rung of the escalation ladder.

    A row, not a constant: a free endpoint can be withdrawn without notice, and
    replacing it must not require a deployment.
    """

    __tablename__ = "ai_models"
    __table_args__ = (
        UniqueConstraint("model_id", name="uq_ai_models_model_id"),
        CheckConstraint("tier >= 1 AND tier <= 3", name="tier_range"),
        Index("ix_ai_models_tier", "tier"),
    )

    tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # Which adapter serves this rung. Existing rows predate the column and are
    # all OpenRouter, so the backfill in the migration that adds it is a fact
    # about history rather than a guess.
    provider: Mapped[AiProvider] = mapped_column(
        vocabulary(AiProvider, "ai_provider_values"),
        nullable=False,
        default=AiProvider.OPENROUTER,
        server_default=AiProvider.OPENROUTER.value,
    )
    prompt_price_per_million: Mapped[Decimal] = mapped_column(
        PRICE, nullable=False, server_default="0"
    )
    completion_price_per_million: Mapped[Decimal] = mapped_column(
        PRICE, nullable=False, server_default="0"
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class AiRequest(IdentityMixin, TimestampMixin, Base):
    """One request to one model, answered or not.

    The prices are copied rather than read through `ai_model_id`, because a
    price is a fact about a moment: repricing a model in the roster must not
    rewrite what a run six weeks ago cost.
    """

    __tablename__ = "ai_requests"
    __table_args__ = (
        Index("ix_ai_requests_requested_at", "requested_at"),
        Index("ix_ai_requests_signal_id", "signal_id"),
        Index("ix_ai_requests_outcome", "outcome"),
    )

    ai_model_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_models.id", ondelete="SET NULL")
    )
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    tier: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    purpose: Mapped[AiPurpose] = mapped_column(
        vocabulary(AiPurpose, "ai_purpose_values"), nullable=False
    )
    # Nullable: a classification request covers a batch and belongs to no single
    # signal. SET NULL rather than CASCADE, because deleting a signal must not
    # delete the record of what was spent on it.
    signal_id: Mapped[UUID | None] = mapped_column(ForeignKey("signals.id", ondelete="SET NULL"))
    batch_size: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    # Integer, not SmallInteger: a prompt can exceed 32767 tokens and a timeout
    # exceeds 32767 milliseconds, and a ledger that overflows is worse than none.
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    http_status: Mapped[int | None] = mapped_column(SmallInteger)
    outcome: Mapped[AiOutcome] = mapped_column(
        vocabulary(AiOutcome, "ai_outcome_values"), nullable=False
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    prompt_price_per_million: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    completion_price_per_million: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(PRICE, nullable=False, server_default="0")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
