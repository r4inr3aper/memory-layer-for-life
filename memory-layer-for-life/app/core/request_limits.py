"""Refuse request bodies larger than the API ever needs, before holding them in memory.

FastAPI reads and parses a JSON body before any dependency runs, the sign-in check
included, so without a limit an anonymous client could make the process buffer a body
of any size. A declared ``Content-Length`` over the limit is refused without reading; a
body sent without one (chunked) is counted as it arrives and refused once it passes it.
"""

import json
from typing import Final

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_TOO_LARGE: Final = "REQUEST_TOO_LARGE"


class _BodyTooLargeError(Exception):
    """The body passed the limit while it was being read."""


class BodySizeLimitMiddleware:
    """Pure ASGI middleware: answers 413 in the API's error format."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self._max_bytes:
            await self._refuse(send)
            return

        received = 0
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    raise _BodyTooLargeError
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, counting_receive, tracking_send)
        except _BodyTooLargeError:
            if response_started:
                raise
            await self._refuse(send)

    async def _refuse(self, send: Send) -> None:
        megabytes = self._max_bytes // (1024 * 1024)
        body = json.dumps(
            {
                "error_code": REQUEST_TOO_LARGE,
                "message": (
                    f"This request is larger than the server accepts ({megabytes} MB). "
                    "Send fewer or smaller files."
                ),
                "detail": None,
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
