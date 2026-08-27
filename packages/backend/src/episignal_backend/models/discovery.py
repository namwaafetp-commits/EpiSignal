from sqlalchemy import Boolean, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin, TimestampMixin

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
