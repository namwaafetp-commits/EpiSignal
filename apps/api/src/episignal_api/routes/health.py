from typing import Annotated, Literal

from episignal_backend.health import ComponentState, DatabaseHealth
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from episignal_api.dependencies import get_database_health

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["alive"]


class Components(BaseModel):
    database: ComponentState
    postgis: ComponentState


class ReadinessResponse(BaseModel):
    status: Literal["ready"]
    components: Components


class NotReadyResponse(BaseModel):
    status: Literal["not_ready"]
    components: Components
    error_code: Literal["DATABASE_NOT_READY"]


@router.get("/live", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    return LivenessResponse(status="alive")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": NotReadyResponse}},
)
def readiness(
    health: Annotated[DatabaseHealth, Depends(get_database_health)],
) -> ReadinessResponse | JSONResponse:
    components = Components(database=health.database, postgis=health.postgis)
    if not health.is_ready:
        payload = NotReadyResponse(
            status="not_ready",
            components=components,
            error_code="DATABASE_NOT_READY",
        )
        return JSONResponse(status_code=503, content=payload.model_dump())
    return ReadinessResponse(status="ready", components=components)
