"""Fans realtime messages out to every backend instance through Redis pub/sub.

Each instance only knows its own sockets (see ``manager``). To reach everyone,
a message is published on ``workspace:{id}``; every instance, including the
one that published it, is pattern-subscribed to ``workspace:*`` and hands what
it receives to its local manager. One delivery path, so nobody gets an event
twice.

Redis only carries messages. It stores nothing: Postgres stays the source of
truth, and a client that may have missed something re-reads it from there.

Failure handling, so a Redis outage degrades to single-instance behaviour
instead of silence:

- A publish that fails, or that happens while this instance is not
  subscribed, is also delivered to local sockets directly.
- When the subscription comes back after a drop, every local socket is closed
  with 1012 (service restart). Events published meanwhile were lost, and
  clients already treat a reconnect as "resync over REST".
"""

import asyncio
import json
import logging
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings
from app.realtime.manager import ConnectionManager, manager
from app.realtime.presence import Presence

logger = logging.getLogger(__name__)

CHANNEL_PREFIX = "workspace:"
# Standard close code: the server is restarting; the client should reconnect.
CLOSE_SERVICE_RESTART = 1012

RETRY_INITIAL_SECONDS = 0.5
RETRY_MAX_SECONDS = 10.0


def channel_for(workspace_id: int) -> str:
    return f"{CHANNEL_PREFIX}{workspace_id}"


class EventBus:
    def __init__(
        self, local: ConnectionManager, redis_url: str | None, client_name: str = "collabspace"
    ) -> None:
        self.local = local
        self.redis_url = redis_url or None
        # Shows in Redis's CLIENT LIST, so an instance's connections can be found.
        self.client_name = client_name
        self._redis: Redis | None = None
        self._listener: asyncio.Task | None = None
        # Set while the pattern subscription is live. Tests wait on it.
        self.subscribed = asyncio.Event()
        self.presence = Presence(self)

    @property
    def redis(self) -> Redis | None:
        return self._redis

    # ---- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if self.redis_url is None:
            logger.warning("REDIS_URL is not set: realtime events reach this instance's sockets only.")
            return
        self._redis = Redis.from_url(
            self.redis_url, decode_responses=True, client_name=self.client_name
        )
        self._listener = asyncio.create_task(self._listen(), name="redis-event-listener")
        self.presence.start()

    async def stop(self) -> None:
        await self.presence.stop()
        if self._listener is not None:
            self._listener.cancel()
            try:
                await self._listener
            except asyncio.CancelledError:
                pass
            self._listener = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        self.subscribed.clear()

    # ---- what routes call --------------------------------------------------

    async def join(self, workspace_id: int, user_id: int, email: str, websocket) -> None:
        """Register an accepted socket and announce the user if they just came online."""
        self.presence.remember_email(user_id, email)
        await self.local.connect(workspace_id, user_id, websocket)
        await self.presence.sync(workspace_id)

    async def leave(self, workspace_id: int, user_id: int, websocket) -> None:
        """Forget a socket that has closed, and announce the user if it was their last."""
        self.local.disconnect(workspace_id, user_id, websocket)
        await self.presence.sync(workspace_id)

    async def broadcast(
        self, workspace_id: int, event: dict, *, exclude_user_id: int | None = None
    ) -> None:
        """Send ``event`` to everyone connected to the workspace, on any instance."""
        await self._send(
            workspace_id, {"kind": "broadcast", "event": event, "exclude_user_id": exclude_user_id}
        )

    async def disconnect_user(self, workspace_id: int, user_id: int, code: int, reason: str) -> None:
        """Close the user's sockets on the workspace, on every instance."""
        await self._send(
            workspace_id,
            {"kind": "disconnect_user", "user_id": user_id, "code": code, "reason": reason},
        )

    # ---- internals ---------------------------------------------------------

    async def _send(self, workspace_id: int, message: dict) -> None:
        published = False
        if self._redis is not None:
            try:
                await self._redis.publish(channel_for(workspace_id), json.dumps(message))
                published = True
            except RedisError:
                logger.warning("Redis publish failed; delivering to local sockets only.", exc_info=True)

        # Our own subscription is what normally delivers locally. Without it
        # (no Redis, publish failed, or the listener is reconnecting), deliver
        # here, or this instance's users would hear nothing either.
        if not (published and self.subscribed.is_set()):
            await self._deliver(workspace_id, message)

    async def _deliver(self, workspace_id: int, message: dict) -> None:
        kind = message.get("kind")
        if kind == "broadcast":
            await self.local.broadcast_to_workspace(
                workspace_id, message["event"], exclude_user_id=message.get("exclude_user_id")
            )
        elif kind == "disconnect_user":
            await self.local.disconnect_user(
                workspace_id, message["user_id"], message["code"], message["reason"]
            )
            await self.presence.sync(workspace_id)
        else:
            logger.warning("Ignoring unknown realtime message kind %r", kind)

    async def _listen(self) -> None:
        delay = RETRY_INITIAL_SECONDS
        dropped = False
        while True:
            pubsub = self._redis.pubsub()
            try:
                await pubsub.psubscribe(f"{CHANNEL_PREFIX}*")
                self.subscribed.set()
                delay = RETRY_INITIAL_SECONDS
                if dropped:
                    await self._reset_local_sockets()
                    dropped = False

                async for raw in pubsub.listen():
                    if raw["type"] != "pmessage":
                        continue
                    await self._handle(raw["channel"], raw["data"])
            except asyncio.CancelledError:
                raise
            except Exception:
                # A Redis or network error. Anything else is a bug in a handler;
                # either way, keep the listener alive rather than going deaf.
                logger.warning("Redis subscription lost; retrying in %.1fs.", delay, exc_info=True)
                if self.subscribed.is_set():
                    dropped = True
                self.subscribed.clear()
                await asyncio.sleep(delay)
                delay = min(delay * 2, RETRY_MAX_SECONDS)
            finally:
                try:
                    await pubsub.aclose()
                except Exception:
                    pass

    async def _handle(self, channel: str, data: str) -> None:
        try:
            workspace_id = int(channel.removeprefix(CHANNEL_PREFIX))
            message: Any = json.loads(data)
        except (ValueError, TypeError):
            logger.warning("Ignoring malformed message on %s", channel)
            return
        try:
            await self._deliver(workspace_id, message)
        except Exception:
            # One bad delivery must not take the listener down with it.
            logger.exception("Failed delivering realtime message on %s", channel)

    async def _reset_local_sockets(self) -> None:
        """After a gap in the subscription, events may have been missed. Close
        every local socket so each client reconnects and resyncs."""
        for workspace_id, users in list(self.local.connections.items()):
            for user_id in list(users):
                await self.local.disconnect_user(
                    workspace_id, user_id, CLOSE_SERVICE_RESTART, "Realtime connection reset"
                )
            await self.presence.sync(workspace_id)


bus = EventBus(manager, settings.redis_url)
