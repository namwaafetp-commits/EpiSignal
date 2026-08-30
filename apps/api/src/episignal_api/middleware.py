"""Request correlation.

Every response carries an `X-Request-ID`. An inbound value is trusted only when
it is a well-formed UUID so that a client cannot inject arbitrary text into the
server logs.
"""

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

logger = logging.getLogger("episignal_api")


def resolve_request_id(inbound: str | None) -> str:
    if inbound is not None:
        try:
            return str(UUID(inbound))
        except ValueError:
            pass
    return str(uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
