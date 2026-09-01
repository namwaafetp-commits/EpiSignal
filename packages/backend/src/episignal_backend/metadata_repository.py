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
