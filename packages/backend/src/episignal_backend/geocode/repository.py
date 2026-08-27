"""The storage boundary for geocoding.

The only module in `geocode/` that imports SQLAlchemy, and the only one that
owns transactions. Deliberately unable to decide anything: it fetches candidates
and writes rows, and the ladder above it chooses.
"""

from collections.abc import Mapping, Sequence
from functools import lru_cache

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from episignal_backend.db.types import Precision
from episignal_backend.geocode.documents import Candidate, MatchForm
from episignal_backend.geocode.normalize import ascii_form, normalized_form
from episignal_backend.models import GazetteerPlace
from episignal_backend.seeds import load_country_aliases

# Two is enough to answer the only question the ladder asks: is this name
# unique here? One row means yes, two means no, and the rest are irrelevant.
CANDIDATE_LIMIT = 2


@lru_cache(maxsize=1)
def _aliases() -> Mapping[str, str]:
    return {alias.name: alias.country_code for alias in load_country_aliases()}


def _candidate(row: GazetteerPlace) -> Candidate:
    return Candidate(
        geonames_id=row.geonames_id,
        name=row.name,
        precision=row.precision,
        country_code=row.country_code,
        admin1_code=row.admin1_code,
        admin2_code=row.admin2_code,
        latitude=row.latitude,
        longitude=row.longitude,
    )


class SqlAlchemyGazetteerRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def country_aliases(self) -> Mapping[str, str]:
        return _aliases()

    def _scoped(
        self, statement: Select[tuple[GazetteerPlace]], country_code: str | None, admin1_code: str | None
    ) -> Select[tuple[GazetteerPlace]]:
        if country_code is not None:
            statement = statement.where(GazetteerPlace.country_code == country_code)
            if admin1_code is not None:
                statement = statement.where(GazetteerPlace.admin1_code == admin1_code)
        return statement

    def candidates(
        self,
        *,
        name: str,
        form: MatchForm,
        country_code: str | None,
        admin1_code: str | None,
    ) -> Sequence[Candidate]:
        if form is MatchForm.EXACT:
            predicate = GazetteerPlace.normalized_name == normalized_form(name)
        elif form is MatchForm.ASCII:
            predicate = GazetteerPlace.ascii_name == ascii_form(name)
        else:
            predicate = GazetteerPlace.alternate_names.any(  # type: ignore[assignment]
                normalized_form(name)
            )
        statement = self._scoped(
            select(GazetteerPlace).where(predicate), country_code, admin1_code
        ).limit(CANDIDATE_LIMIT)
        return tuple(_candidate(row) for row in self._session.execute(statement).scalars())

    def admin1_code(self, *, country_code: str, name: str) -> str | None:
        return self._session.execute(
            select(GazetteerPlace.admin1_code)
            .where(
                GazetteerPlace.country_code == country_code,
                GazetteerPlace.precision == Precision.ADMIN1,
                or_(
                    GazetteerPlace.normalized_name == normalized_form(name),
                    GazetteerPlace.ascii_name == ascii_form(name),
                ),
            )
            .limit(1)
        ).scalar_one_or_none()

    def centroid(self, *, country_code: str, admin1_code: str | None) -> Candidate | None:
        precision = Precision.COUNTRY if admin1_code is None else Precision.ADMIN1
        statement = select(GazetteerPlace).where(
            GazetteerPlace.country_code == country_code,
            GazetteerPlace.precision == precision,
        )
        if admin1_code is not None:
            statement = statement.where(GazetteerPlace.admin1_code == admin1_code)
        row = self._session.execute(statement.limit(1)).scalar_one_or_none()
        return None if row is None else _candidate(row)
