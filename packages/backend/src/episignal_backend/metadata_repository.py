"""SQLAlchemy adapter for the reviewed local metadata references."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from episignal_backend.db.types import Precision
from episignal_backend.metadata import (
    Admin1VocabularyEntry,
    DiseaseVocabularyEntry,
    LocalMetadataResolver,
)
from episignal_backend.models import Disease, GazetteerPlace
from episignal_backend.seeds import load_country_aliases


def event_display_location(
    session: Session, *, country_code: str | None, admin1: str | None
) -> str:
    """Return a local, human-readable event location without network lookup."""
    if country_code is None:
        return "Unresolved location"

    statement = select(GazetteerPlace.name, GazetteerPlace.precision).where(
        GazetteerPlace.country_code == country_code
    )
    if admin1 is not None:
        statement = statement.where(GazetteerPlace.admin1_code == admin1)
    rows = session.execute(statement).all()
    admin1_name = next((name for name, precision in rows if precision is Precision.ADMIN1), None)
    country_name = next((name for name, precision in rows if precision is Precision.COUNTRY), None)
    if country_name is None:
        # A country-only fallback query is needed when the admin1 filter above
        # correctly excludes the country row.
        country_name = session.execute(
            select(GazetteerPlace.name)
            .where(
                GazetteerPlace.country_code == country_code,
                GazetteerPlace.precision == Precision.COUNTRY,
            )
            .limit(1)
        ).scalar_one_or_none()
    if country_name is None:
        return "Unresolved location"
    if admin1_name and country_name:
        return f"{admin1_name}, {country_name}"
    return country_name or "Unresolved location"


def local_metadata_resolver(session: Session) -> LocalMetadataResolver:
    aliases = {alias.name: alias.country_code for alias in load_country_aliases()}
    disease_result = session.execute(select(Disease).order_by(Disease.id))
    # Small repository fakes used by the event seam expose only joined-row
    # results. Seed aliases still let those seams exercise country behavior;
    # production SQLAlchemy results carry the reviewed disease/gazetteer data.
    if not hasattr(disease_result, "scalars"):
        return LocalMetadataResolver(
            country_aliases=aliases,
            country_codes=tuple(aliases.values()),
        )
    diseases = disease_result.scalars().all()
    admin1s = (
        session.execute(
            select(GazetteerPlace)
            .where(GazetteerPlace.precision == Precision.ADMIN1)
            .order_by(GazetteerPlace.geonames_id)
        )
        .scalars()
        .all()
    )
    country_codes = session.execute(select(GazetteerPlace.country_code).distinct()).scalars().all()
    return LocalMetadataResolver(
        country_aliases=aliases,
        country_codes=tuple(country_codes),
        diseases=tuple(
            DiseaseVocabularyEntry(
                id=row.id,
                canonical_name=row.canonical_name,
                slug=row.slug,
                synonyms=tuple(row.synonyms),
            )
            for row in diseases
        ),
        admin1s=tuple(
            Admin1VocabularyEntry(
                name=row.name,
                country_code=row.country_code,
                code=row.admin1_code,
                alternate_names=tuple(row.alternate_names),
            )
            for row in admin1s
            if row.admin1_code is not None
        ),
    )
