from sqlalchemy import Boolean, CheckConstraint, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from episignal_backend.db.base import Base, IdentityMixin, TimestampMixin
from episignal_backend.db.types import CredibilityTier, SourceType, vocabulary


class Source(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (CheckConstraint("length(country_code) = 2", name="country_code_alpha2"),)

    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    source_type: Mapped[SourceType] = mapped_column(
        vocabulary(SourceType, "source_type_values"),
        nullable=False,
    )
    country_code: Mapped[str | None] = mapped_column(String(2))
    base_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    feed_url: Mapped[str | None] = mapped_column(Text, unique=True)
    domain: Mapped[str | None] = mapped_column(Text, unique=True)
    credibility_tier: Mapped[CredibilityTier] = mapped_column(

        vocabulary(CredibilityTier, "credibility_tier_values"),
        nullable=False,
        default=CredibilityTier.UNKNOWN,
    )
    is_official: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Disease(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "diseases"

    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    icd10: Mapped[str | None] = mapped_column(String(16))
    synonyms: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
    category: Mapped[str | None] = mapped_column(Text)


class Pathogen(IdentityMixin, TimestampMixin, Base):
    __tablename__ = "pathogens"

    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    taxonomy: Mapped[str | None] = mapped_column(Text)
    synonyms: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}"
    )
