import secrets
from datetime import UTC, datetime
from typing import Annotated

from episignal_backend.config import get_settings
from episignal_backend.db.session import connection_scope, session_scope
from episignal_backend.evidence import EvidencePage, query_evidence_page
from episignal_backend.health import DatabaseHealth, check_database
from episignal_backend.radar import PipelineRunPage, RadarPage, query_pipeline_runs, query_radar
from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer_scheme = HTTPBearer(auto_error=False)


def verify_admin_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> str:
    """Validate administrator token via Bearer header or X-Admin-Token header."""
    settings = get_settings()
    expected = (
        settings.review_admin_token.get_secret_value()
        if settings.review_admin_token
        else None
    )

    provided: str | None = None
    if credentials and credentials.credentials:
        provided = credentials.credentials
    elif x_admin_token:
        provided = x_admin_token

    if expected is not None:
        if provided is None or not secrets.compare_digest(provided, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: invalid or missing admin token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return "admin"

    if settings.env == "production":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin token is not configured in production",
        )

    if provided is not None:
        return "admin"
    return "dev-admin"


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


def get_pipeline_runs_page(
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> PipelineRunPage:
    settings = get_settings()
    with session_scope() as session:
        now = datetime.now(UTC)
        return query_pipeline_runs(
            session,
            now=now,
            stale_after_minutes=settings.gdelt_poll_interval_minutes,
            limit=limit,
        )
