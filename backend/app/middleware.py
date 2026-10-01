"""Per-request context: a request id, an access log line, and the last-resort
catch for unexpected exceptions.

Plain ASGI rather than BaseHTTPMiddleware, so it does not buffer responses or
interfere with background tasks. WebSocket traffic passes straight through;
the socket route logs its own lifecycle.
"""

import logging
import re
import time
import uuid

from app.errors import error_response
from app.logging_config import request_id_var

logger = logging.getLogger("app.request")

# Accept a caller's id (e.g. from a proxy) only if it looks like one.
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
# Health checks run every few seconds; logging them at INFO buries everything else.
_QUIET_PATHS = {"/health"}


class RequestContextMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        try:
            if scope["type"] == "websocket":
                await self.app(scope, receive, send)
            else:
                await self._http(scope, receive, send, request_id)
        finally:
            request_id_var.reset(token)

    async def _http(self, scope, receive, send, request_id: str) -> None:
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_id(message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status = message["status"]
                response_started = True
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", request_id.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            # Nothing above handled it. The client gets a generic 500 with the
            # request id; the traceback stays in our log.
            logger.exception("unhandled error", extra={"event": "request.error", "path": scope["path"]})
            if not response_started:
                status = 500
                response = error_response(500, "Something went wrong on our side.")
                await response(scope, receive, send_with_id)
        finally:
            path = scope["path"]  # never the query string: it can carry a token
            level = logging.DEBUG if path in _QUIET_PATHS else logging.INFO
            logger.log(
                level,
                f"{scope['method']} {path} {status}",
                extra={
                    "event": "request",
                    "method": scope["method"],
                    "path": path,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
