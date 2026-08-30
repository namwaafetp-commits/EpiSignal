"""Pre-group storage: routing decisions made before any AI call.

A `story_groups` row is a pre-group — one rule group, one country, one time
chain — and its members link signals to their role. Membership is routing,
never judgement: nothing here touches evidence, and deferral ends the moment
the group resolves or expires, returning every deferred signal to normal
selection without moving its processing status.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin, TimestampMixin
from episignal_backend.db.types import StoryGroupRole, StoryGroupState, vocabulary


class StoryGroup(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "story_groups"
    __table_args__ = (
        Index("ix_story_groups_state", "state"),
        Index("ix_story_groups_window", "rule_group", "country_code"),
    )

    rule_group: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str | None] = mapped_column(String(2))
    state: Mapped[StoryGroupState] = mapped_column(
        vocabulary(StoryGroupState, "story_group_state_values"),
        nullable=False,
        default=StoryGroupState.OPEN,
        server_default=StoryGroupState.OPEN.value,
    )
    window_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoryGroupMember(IdentityMixin, Base):
    __tablename__ = "story_group_members"
    __table_args__ = (
        UniqueConstraint("signal_id", name="uq_story_group_members_signal"),
        Index("ix_story_group_members_group", "group_id"),
        Index("ix_story_group_members_role", "role"),
    )

    group_id: Mapped[UUID] = mapped_column(
        ForeignKey("story_groups.id", ondelete="CASCADE"), nullable=False
    )
    signal_id: Mapped[UUID] = mapped_column(
        ForeignKey("signals.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[StoryGroupRole] = mapped_column(
        vocabulary(StoryGroupRole, "story_group_role_values"),
        nullable=False,
    )
