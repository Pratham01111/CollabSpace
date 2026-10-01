"""Tracks the open WebSocket connections for each workspace.

Everything here runs on the event loop, so reads and writes of ``connections``
between two ``await``s cannot interleave with another coroutine; no lock needed.
State is per process: this only knows the sockets connected to this instance.
``app.realtime.bus`` is what reaches the sockets on other instances.
"""

from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

# Application close codes (4000-4999), modelled on the matching HTTP statuses.
CLOSE_UNAUTHORIZED = 4401
# Not a member and no such workspace look the same, as they do over REST: a
# distinct code would confirm that someone else's workspace exists. Also sent
# to a member's open sockets when they leave or are removed.
CLOSE_WORKSPACE_NOT_FOUND = 4404


class ConnectionManager:
    def __init__(self) -> None:
        # workspace_id -> user_id -> that user's sockets. A set, not a single
        # socket, because the same person may have the board open in two tabs
        # and both should stay live.
        self.connections: dict[int, dict[int, set[WebSocket]]] = {}

    async def connect(self, workspace_id: int, user_id: int, websocket: WebSocket) -> None:
        """Register an already-accepted socket."""
        self.connections.setdefault(workspace_id, {}).setdefault(user_id, set()).add(websocket)

    def disconnect(self, workspace_id: int, user_id: int, websocket: WebSocket) -> None:
        """Forget this socket. Safe to call more than once."""
        workspace = self.connections.get(workspace_id)
        if workspace is None:
            return
        sockets = workspace.get(user_id)
        if sockets is None:
            return

        sockets.discard(websocket)
        if not sockets:
            del workspace[user_id]
        if not workspace:
            del self.connections[workspace_id]

    async def disconnect_user(self, workspace_id: int, user_id: int, code: int, reason: str) -> None:
        """Close every socket a user has open on a workspace — e.g. once they
        are no longer a member, so they stop receiving its events."""
        sockets = self.connections.get(workspace_id, {}).get(user_id, set())
        for websocket in list(sockets):
            self.disconnect(workspace_id, user_id, websocket)
            await _close_quietly(websocket, code, reason)

    def connected_user_ids(self, workspace_id: int) -> list[int]:
        return sorted(self.connections.get(workspace_id, {}))

    async def send_to_user(self, workspace_id: int, user_id: int, message: Any) -> bool:
        """Send ``message`` as JSON to each of the user's sockets. Returns
        whether it reached at least one; sockets that fail are dropped."""
        sockets = self.connections.get(workspace_id, {}).get(user_id, set())
        delivered = False
        for websocket in list(sockets):
            delivered |= await self._send(workspace_id, user_id, websocket, message)
        return delivered

    async def broadcast_to_workspace(
        self, workspace_id: int, message: Any, *, exclude_user_id: int | None = None
    ) -> None:
        """Send ``message`` as JSON to everyone connected to the workspace.

        ``exclude_user_id`` is there for the usual "don't echo the sender's own
        change back to them" case.
        """
        # Snapshot: a failed send removes its entry while we are iterating.
        for user_id in list(self.connections.get(workspace_id, {})):
            if user_id != exclude_user_id:
                await self.send_to_user(workspace_id, user_id, message)

    async def _send(self, workspace_id: int, user_id: int, websocket: WebSocket, message: Any) -> bool:
        try:
            await websocket.send_json(message)
            return True
        except Exception:
            # The peer vanished without a clean close. One dead socket must not
            # stop a broadcast reaching everyone else.
            self.disconnect(workspace_id, user_id, websocket)
            return False


async def _close_quietly(websocket: WebSocket, code: int, reason: str) -> None:
    if websocket.application_state != WebSocketState.CONNECTED:
        return
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        pass


manager = ConnectionManager()
