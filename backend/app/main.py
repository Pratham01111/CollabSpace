from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import configure_logging

# Before anything else logs, so every line uses the same format.
configure_logging(settings.log_level, settings.log_format)

from app.auth.routes import router as auth_router  # noqa: E402
from app.comments.routes import router as comments_router  # noqa: E402
from app.errors import install_error_handlers  # noqa: E402
from app.middleware import RequestContextMiddleware  # noqa: E402
from app.realtime.bus import bus  # noqa: E402
from app.realtime.routes import router as realtime_router  # noqa: E402
from app.tasks.routes import tasks_router, workspace_tasks_router  # noqa: E402
from app.workspaces.routes import router as workspaces_router  # noqa: E402

DESCRIPTION = """
A real-time collaborative workspace: Kanban boards, comments and presence.

**Auth.** `POST /auth/login` returns an access token. Send it on every other
request as `Authorization: Bearer <token>`.

**Errors.** Every error has the same body:
`{"detail": "...", "code": "...", "request_id": "..."}`, plus `errors` (per field)
on a 422. The request id is also in the `X-Request-ID` response header.

**Access.** A workspace you are not a member of, and everything in it, is a
404, never a 403, so its existence is not revealed.

**Concurrency.** `PATCH /tasks/{id}` must send `expected_version`. A stale one
is a 409 carrying `current_task`.

**Live updates (WebSocket, not listed below).**
`GET /ws/workspaces/{id}?token=<access_token>` upgrades to a WebSocket. The
server sends `connected` (with `online_users`), then `TASK_CREATED`,
`TASK_UPDATED`, `TASK_DELETED`, `COMMENT_CREATED`, `USER_JOINED` and
`USER_LEFT` as they happen. Send the text `ping` to get `{"type": "pong"}`.
Close codes: 4401 bad token, 4404 not a member, 1013 try again later.
"""

TAGS = [
    {"name": "auth", "description": "Register, log in, and the current user."},
    {"name": "workspaces", "description": "Workspaces and their membership."},
    {"name": "tasks", "description": "Board tasks, version-checked on update."},
    {"name": "comments", "description": "Comments on a task."},
    {"name": "health", "description": "Liveness."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Subscribe to Redis so events published by any instance reach this one's sockets.
    await bus.start()
    yield
    await bus.stop()


app = FastAPI(
    title="CollabSpace API",
    version="1.0.0",
    description=DESCRIPTION,
    openapi_tags=TAGS,
    lifespan=lifespan,
)

install_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
# Added last, so it runs first: every request, CORS preflights included, gets
# an id and a log line.
app.add_middleware(RequestContextMiddleware)


app.include_router(auth_router)
app.include_router(workspaces_router)
app.include_router(workspace_tasks_router)
app.include_router(tasks_router)
app.include_router(comments_router)
app.include_router(realtime_router)


@app.get("/health", tags=["health"], summary="Liveness check")
def health():
    """Always `{"status": "ok"}` while the process is serving requests."""
    return {"status": "ok"}
