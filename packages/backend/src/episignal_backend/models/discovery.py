from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin, TimestampMixin
from episignal_backend.db.types import FilterRuleGroup, vocabulary

ANY_LANGUAGE = "any"


class GdeltQueryRule(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "gdelt_query_rules"
    __table_args__ = (UniqueConstraint("query", "language", name="uq_gdelt_query_rules_query"),)

    rule_group: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # Not nullable: PostgreSQL treats NULLs as distinct, so a nullable column
    # would let the same unrestricted query be seeded without limit.
    language: Mapped[str] = mapped_column(
        Text, nullable=False, default=ANY_LANGUAGE, server_default=ANY_LANGUAGE
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class SignalFilterRule(IdentityMixin, TimestampMixin, Base):
    """A Stage 0 rule, editable in the database without a deployment.

    Named apart from the `FilterRule` contract for the same reason
    `GdeltQueryRule` is named apart from `QueryRule`: one is a row, the other is
    what the pipeline is handed.
    """

    __tablename__ = "filter_rules"
    __table_args__ = (UniqueConstraint("rule_group", "pattern", name="uq_filter_rules_rule_group"),)

    rule_group: Mapped[FilterRuleGroup] = mapped_column(
        vocabulary(FilterRuleGroup, "filter_rule_group_values"), nullable=False
    )
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class RejectedSighting(IdentityMixin, TimestampMixin, Base):
    """An article dropped before its page was fetched.

    Deliberately not a `signals` row: `signals.retrieved_at` and
    `signals.content_hash` are both NOT NULL, and this article was never
    retrieved and has no body, so storing it there would mean inventing a
    retrieval time.
    """

    __tablename__ = "rejected_sightings"
    __table_args__ = (
        UniqueConstraint("canonical_url", name="uq_rejected_sightings_canonical_url"),
        Index("ix_rejected_sightings_filter_rule_id", "filter_rule_id"),
        Index("ix_rejected_sightings_rejected_at", "rejected_at"),
    )

    url: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    gdelt_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # SET NULL, matching signals.query_rule_id: retiring a rule must not delete
    # the record of what it rejected.
    filter_rule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("filter_rules.id", ondelete="SET NULL")
    )
