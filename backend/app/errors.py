"""One error shape for every failure, and nothing internal leaking out.

Every error response, whatever raised it, looks like:

    {"detail": "Human-readable message.", "code": "machine_readable", "request_id": "..."}

plus ``errors`` (per-field problems) on a 422, and anything a route adds on
purpose (the 409 on a task carries ``current_task``). ``detail`` stays a plain
string so clients can always show it.

Validation errors never echo what was submitted: FastAPI's default includes
the input, which for a rejected password means repeating the password.
Unexpected exceptions become a generic 500. The traceback goes to the log,
tagged with the request id the client also receives.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging_config import request_id_var

logger = logging.getLogger("app.errors")

_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "too_many_requests",
    500: "internal_error",
    503: "service_unavailable",
}


class FieldError(BaseModel):
    field: str
    message: str


class ErrorResponse(BaseModel):
    """The body of every error response."""

    detail: str
    code: str
    request_id: str | None = None
    errors: list[FieldError] | None = None


def error_response(
    status: int, detail: str, code: str | None = None, headers: dict | None = None, **extra: Any
) -> JSONResponse:
    body = {
        "detail": detail,
        "code": code or _CODES.get(status, "error"),
        "request_id": request_id_var.get(),
        **extra,
    }
    return JSONResponse(status_code=status, content=body, headers=headers)


def _field(loc: tuple | list) -> str:
    # ("body", "password") -> "password"; ("path", "task_id") -> "task_id"
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(parts) or "body"


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else _CODES.get(exc.status_code, "Error")
    return error_response(exc.status_code, detail, headers=getattr(exc, "headers", None))


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"field": _field(e.get("loc", ())), "message": e.get("msg", "Invalid value.")}
        for e in exc.errors()
    ]
    first = errors[0] if errors else {"field": "body", "message": "Invalid request."}
    summary = first["message"] if first["field"] == "body" else f"{first['field']}: {first['message']}"
    logger.info(
        "request rejected by validation",
        extra={"event": "request.invalid", "fields": [e["field"] for e in errors]},
    )
    return error_response(422, summary, errors=errors)


async def _database_unavailable(request: Request, exc: DBAPIError) -> JSONResponse:
    # Lost or refused connection. The pool's pre-ping replaces dead
    # connections, so this clears as soon as the database is back.
    if isinstance(exc, OperationalError) or exc.connection_invalidated:
        logger.error("database unavailable", extra={"event": "db.unavailable"}, exc_info=exc)
        return error_response(
            503, "The service is temporarily unavailable. Please try again.", "database_unavailable"
        )
    logger.exception("database error", extra={"event": "db.error"}, exc_info=exc)
    return error_response(500, "Something went wrong on our side.")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(DBAPIError, _database_unavailable)
    # Anything else is caught by RequestContextMiddleware, which can still
    # send a response; a handler for bare Exception would let Starlette
    # re-raise and log the traceback a second time.


_DOC_DESCRIPTIONS = {
    401: "Missing, invalid or expired token.",
    403: "Your role in this workspace does not allow it.",
    404: "Not found, or not visible to you (the two are deliberately indistinguishable).",
    409: "Conflicts with the current state.",
    422: "The request failed validation; `errors` lists each field.",
}


def error_docs(*statuses: int, **descriptions: str) -> dict[int | str, dict]:
    """``responses=`` for a route: the error statuses it can return, all with
    the shared ErrorResponse body. ``descriptions`` overrides by status, e.g.
    ``error_docs(404, 409, s409="Already a member.")``."""
    return {
        status: {
            "model": ErrorResponse,
            "description": descriptions.get(f"s{status}", _DOC_DESCRIPTIONS.get(status, "Error.")),
        }
        for status in statuses
    }
