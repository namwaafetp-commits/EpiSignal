"""Application composition.

`create_app` never connects to the database; it only wires already validated
settings. `load_runtime_settings` turns configuration failures into short stderr
guidance that names the environment variable but never echoes its value.
"""

import logging
import sys
from typing import Any
from uuid import uuid4

from episignal_backend.config import Settings, get_settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.requests import Request

from episignal_api import API_NAME, API_VERSION
from episignal_api.middleware import REQUEST_ID_HEADER, RequestIDMiddleware
from episignal_api.routes import admin, health, radar, reviews, signals, version

logger = logging.getLogger("episignal_api")


async def handle_unexpected_error(request: Request, exception: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    logger.exception("Unhandled request failure request_id=%s", request_id)
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred.",
            "request_id": request_id,
        },
        headers={REQUEST_ID_HEADER: request_id},
    )


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title=API_NAME, version=API_VERSION)
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestIDMiddleware)

    app.include_router(health.router)
    app.include_router(version.router)
    app.include_router(signals.router)
    app.include_router(radar.router)
    app.include_router(admin.router)
    app.include_router(reviews.router)

    app.add_exception_handler(Exception, handle_unexpected_error)
    return app


def _environment_name(location: tuple[Any, ...]) -> str:
    field = location[0] if location else "settings"
    return f"EPISIGNAL_{str(field).upper()}"


def describe_settings_errors(error: ValidationError) -> list[str]:
    return [
        f"{_environment_name(item['loc'])}: {item['msg']}"
        for item in error.errors(include_url=False, include_input=False)
    ]


def load_runtime_settings() -> Settings:
    try:
        return get_settings()
    except ValidationError as error:
        print("EpiSignal configuration is invalid:", file=sys.stderr)
        for line in describe_settings_errors(error):
            print(f"  {line}", file=sys.stderr)
        print("Copy apps/api/.env.example to apps/api/.env and fill it in.", file=sys.stderr)
        raise SystemExit(1) from None
