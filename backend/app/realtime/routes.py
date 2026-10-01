"""WS /ws/workspaces/{workspace_id}: an authenticated live channel per workspace.

Connect with the access token as a query parameter:

    ws://localhost:8000/ws/workspaces/1?token=<access_token>

Browsers cannot set an Authorization header on a WebSocket, hence the query
parameter.
"""

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.auth.dependencies import InvalidTokenError, user_from_token
from app.database.database import SessionLocal
from app.realtime.manager import CLOSE_UNAUTHORIZED, CLOSE_WORKSPACE_NOT_FOUND, manager
from app.workspaces import service as workspace_service

router = APIRouter(tags=["realtime"])


class _Rejected(Exception):
    def __init__(self, code: int, reason: str) -> None:
        self.code = code
        self.reason = reason


def _authorize(token: str | None, workspace_id: int) -> int:
    """The connecting user's id, or ``_Rejected``. Same rules as REST.

    Uses its own short-lived session rather than ``get_db``: a dependency's
    session would stay checked out of the pool for as long as the socket is open.
    """
    if not token:
        raise _Rejected(CLOSE_UNAUTHORIZED, "Not authenticated")

    with SessionLocal() as db:
        try:
            user = user_from_token(db, token)
        except InvalidTokenError as exc:
            raise _Rejected(CLOSE_UNAUTHORIZED, str(exc)) from None

        if workspace_service.get_membership(db, workspace_id, user.id) is None:
            raise _Rejected(CLOSE_WORKSPACE_NOT_FOUND, "Workspace not found.")

        return user.id


@router.websocket("/ws/workspaces/{workspace_id}")
async def workspace_socket(
    websocket: WebSocket,
    workspace_id: int,
    token: str | None = Query(default=None),
) -> None:
    # Accept before checking: a socket refused during the handshake reaches the
    # client as a bare HTTP 403, with no close code or reason to say why.
    await websocket.accept()

    try:
        # The database calls are blocking; keep them off the event loop.
        user_id = await run_in_threadpool(_authorize, token, workspace_id)
    except _Rejected as rejection:
        await websocket.close(code=rejection.code, reason=rejection.reason)
        return

    await manager.connect(workspace_id, user_id, websocket)
    try:
        await websocket.send_json(
            {
                "type": "connected",
                "workspace_id": workspace_id,
                "user_id": user_id,
                "connected_user_ids": manager.connected_user_ids(workspace_id),
            }
        )

        # Events are pushed by the REST routes via the manager; clients send
        # nothing but pings, so this loop just notices when they go away.
        while True:
            if (await websocket.receive_text()).strip() == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(workspace_id, user_id, websocket)
