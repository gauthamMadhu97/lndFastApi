"""Request reference, timing and access logging (8.1 - 8.4).

Written as plain ASGI middleware rather than BaseHTTPMiddleware so it doesn't buffer
responses and so the log is written when the response finishes, not after any
background tasks that run afterwards.
"""

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import request_id_ctx
from app.core.errors import error_body

access_log = logging.getLogger("assetdesk.access")
error_log = logging.getLogger("assetdesk.errors")

REQUEST_ID_HEADER = "X-Request-ID"
PROCESS_TIME_HEADER = "X-Process-Time-Ms"
# Accept a caller's id only if it looks sane, so nobody can inject junk into our logs
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        status_code = 500
        finished_at: float | None = None

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code, finished_at
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                headers[PROCESS_TIME_HEADER] = f"{(time.perf_counter() - start) * 1000:.2f}"
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                finished_at = time.perf_counter()
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            elapsed_ms = ((finished_at or time.perf_counter()) - start) * 1000
            route = scope.get("route")
            access_log.info(
                "request",
                extra={
                    "fields": {
                        "request_id": request_id,
                        "method": scope["method"],
                        "operation": getattr(route, "name", None),
                        "path": getattr(route, "path", scope["path"]),
                        "status": status_code,
                        "outcome": "success" if status_code < 400 else "failure",
                        "duration_ms": round(elapsed_ms, 2),
                    }
                },
            )
            request_id_ctx.reset(token)


class UnhandledErrorMiddleware:
    """Turns an unexpected exception into a JSON 500.

    Sits inside CORS and RequestContextMiddleware, so a crash still gets CORS headers,
    a request id, timing and an access log line (8.4).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            error_log.exception("unhandled error", extra={"fields": {"path": scope["path"]}})
            if response_started:
                raise
            response = JSONResponse(
                error_body("INTERNAL_ERROR", "Something went wrong. Quote the request id if you report it."),
                status_code=500,
            )
            await response(scope, receive, send)
