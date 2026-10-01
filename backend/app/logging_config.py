"""Structured logging: one JSON object per line, on stdout.

Every record carries the request id of the request it was logged under (see
``app.middleware``), so the lines for one request can be pulled out of a busy
log. Pass event-specific fields through ``extra``:

    logger.info("login failed", extra={"event": "auth.login_failed", "email": email})

LOG_FORMAT=text gives plain lines instead, which is easier to read when running
locally.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# Set per request by the middleware; read by the formatter and error handlers.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else came from ``extra``.
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None)))
_STANDARD |= {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            entry["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extras = {k: v for k, v in vars(record).items() if k not in _STANDARD and not k.startswith("_")}
        line = f"{record.levelname:<7} {record.name}: {record.getMessage()}"
        if extras:
            line += "  " + " ".join(f"{k}={v}" for k, v in extras.items())
        request_id = request_id_var.get()
        if request_id:
            line += f"  request_id={request_id}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(TextFormatter() if fmt == "text" else JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # Route uvicorn's own loggers through the same handler and format.
    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True
    # Requests are logged by our middleware instead: uvicorn's access log
    # would duplicate them, and it records query strings, which for the
    # WebSocket include the access token.
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    access.disabled = True
