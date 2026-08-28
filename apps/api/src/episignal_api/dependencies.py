"""Injectable database reads.

Routes depend on these callables rather than opening sessions themselves, so
unit tests can override them and never reach the hosted project.
"""

from datetime import UTC, datetime
from typing import Annotated

from episignal_backend.db.session import connection_scope, session_scope
from episignal_backend.evidence import EvidencePage, query_evidence_page
from episignal_backend.health import DatabaseHealth, check_database
from episignal_backend.radar import RadarPage, query_radar
from fastapi import Query


def get_database_health() -> DatabaseHealth:
    try:
        with connection_scope() as connection:
            return check_database(connection)
    except Exception:
        return DatabaseHealth(database="down", postgis="unknown")


def get_evidence_page(
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EvidencePage:
    with session_scope() as session:
        return query_evidence_page(session, limit=limit, offset=offset)


def get_radar_page(
    hours: Annotated[int, Query(ge=1, le=168)] = 48,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RadarPage:
    with session_scope() as session:
        now = datetime.now(UTC)
        return query_radar(session, now=now, hours=hours, limit=limit)
