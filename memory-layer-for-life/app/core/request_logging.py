"""One log line per HTTP request, and a request id on everything logged during it.

The id is taken from the ``X-Request-ID`` header when a client sends one, so a client
and the server can talk about the same request. Otherwise one is made up. It is
returned in the response and bound to the logging context for the whole request,
including the background processing a request starts.

Only the method, the path, the status, and the duration are logged. Query strings and
bodies carry personal messages and are never written to the log.
"""

import re
import time
import uuid
from typing import Final

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER: Final = "x-request-id"
_ACCEPTED_REQUEST_ID: Final = re.compile(r"[A-Za-z0-9._-]{1,128}")


def request_id_for(headers: Headers) -> str:
    """The client's request id when it is safe to log, otherwise a fresh one."""
    offered = headers.get(REQUEST_ID_HEADER)
    if offered is not None and _ACCEPTED_REQUEST_ID.fullmatch(offered):
        return offered
    return uuid.uuid4().hex


class RequestLoggingMiddleware:
    """Pure ASGI middleware, so it adds no buffering around the response."""

    def __init__(self, app: ASGIApp, *, api_prefix: str) -> None:
        self._app = app
        self._api_prefix = api_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = request_id_for(Headers(scope=scope))
        method = str(scope.get("method", ""))
        path = str(scope.get("path", ""))
        status_code: int | None = None
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            await self._app(scope, receive, send_with_request_id)
        except Exception:
            # The outermost error handler answers with 500 after this re-raise.
            status_code = status_code or 500
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000)
            # Requests for the web UI's files are noise; API requests are the record.
            log = logger.info if path.startswith(self._api_prefix) else logger.debug
            log(
                "http_request",
                request_id=request_id,
                method=method,
                path=path,
                status=status_code,
                duration_ms=duration_ms,
            )
            structlog.contextvars.unbind_contextvars("request_id")
