"""Who is online in each workspace, across every backend instance.

Ephemeral by design: nothing here touches Postgres.

With Redis, each workspace has a sorted set ``presence:{id}``. Its members are
``"{user_id}:{instance_id}"``, one per user per instance that has them
connected, scored with an expiry time. A user is online while any of their
members is unexpired, so two tabs, or two tabs on two servers, count once.

- Each instance refreshes its own members every ``HEARTBEAT_SECONDS``. If an
  instance dies, its members lapse after ``TTL_SECONDS``, and the next sweep by
  any instance still serving that workspace announces those users as gone.
- USER_JOINED goes out when a user's first member appears, and USER_LEFT when
  their last one disappears. Each change is a MULTI transaction that also reads
  what is left, so "was that the last one?" is answered atomically.

Without Redis, the local ConnectionManager is the whole truth.

Changes are never made directly from connect/disconnect. ``sync()`` compares
the users this instance has sockets for with those it has registered, and
fixes the difference. Every way a socket can go away (clean close, kick, failed
send, a reset after a Redis outage) therefore ends in the same place.
"""

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING

from redis.exceptions import RedisError

if TYPE_CHECKING:
    from app.realtime.bus import EventBus

logger = logging.getLogger(__name__)

TTL_SECONDS = 30
HEARTBEAT_SECONDS = 10
KEY_PREFIX = "presence:"


def presence_key(workspace_id: int) -> str:
    return f"{KEY_PREFIX}{workspace_id}"


def _user_of(member: str) -> int:
    return int(member.split(":", 1)[0])


class Presence:
    def __init__(self, bus: "EventBus") -> None:
        self.bus = bus
        self.instance_id = uuid.uuid4().hex[:12]
        # workspace_id -> users this instance has announced as present there.
        self._registered: dict[int, set[int]] = {}
        self._emails: dict[int, str] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._heartbeat: asyncio.Task | None = None

    # ---- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self.bus.redis is not None:
            self._heartbeat = asyncio.create_task(self._beat(), name="presence-heartbeat")

    async def stop(self) -> None:
        if self._heartbeat is not None:
            self._heartbeat.cancel()
            try:
                await self._heartbeat
            except asyncio.CancelledError:
                pass
            self._heartbeat = None
        # Best effort: withdraw our members now rather than leaving them to lapse.
        redis = self.bus.redis
        if redis is not None:
            try:
                for workspace_id, users in self._registered.items():
                    if users:
                        await redis.zrem(presence_key(workspace_id), *(self._member(u) for u in users))
            except RedisError:
                pass
        self._registered.clear()

    # ---- queries -----------------------------------------------------------

    async def online_user_ids(self, workspace_id: int) -> list[int]:
        redis = self.bus.redis
        if redis is None:
            return self.bus.local.connected_user_ids(workspace_id)
        try:
            members = await redis.zrangebyscore(presence_key(workspace_id), time.time(), "+inf")
        except RedisError:
            logger.warning("Presence read failed; reporting this instance's users only.", exc_info=True)
            return self.bus.local.connected_user_ids(workspace_id)
        return sorted({_user_of(m) for m in members})

    # ---- changes -----------------------------------------------------------

    def remember_email(self, user_id: int, email: str) -> None:
        self._emails[user_id] = email

    async def sync(self, workspace_id: int) -> None:
        """Bring Redis (and everyone's "Online now") in line with the sockets
        this instance actually holds for the workspace."""
        lock = self._locks.setdefault(workspace_id, asyncio.Lock())
        async with lock:
            local = set(self.bus.local.connected_user_ids(workspace_id))
            registered = self._registered.setdefault(workspace_id, set())

            for user_id in sorted(local - registered):
                registered.add(user_id)
                if await self._add(workspace_id, user_id):
                    await self.bus.broadcast(
                        workspace_id,
                        {"type": "USER_JOINED", "user": self._user(user_id)},
                        exclude_user_id=user_id,
                    )

            for user_id in sorted(registered - local):
                registered.discard(user_id)
                if await self._remove(workspace_id, user_id):
                    await self._announce_left(workspace_id, user_id)

            if not registered:
                del self._registered[workspace_id]

    # ---- internals ---------------------------------------------------------

    def _member(self, user_id: int) -> str:
        return f"{user_id}:{self.instance_id}"

    def _user(self, user_id: int) -> dict:
        user = {"id": user_id}
        if user_id in self._emails:
            user["email"] = self._emails[user_id]
        return user

    async def _announce_left(self, workspace_id: int, user_id: int) -> None:
        await self.bus.broadcast(workspace_id, {"type": "USER_LEFT", "user": self._user(user_id)})

    async def _add(self, workspace_id: int, user_id: int) -> bool:
        """Register this instance's member. True if the user was offline
        everywhere until now."""
        redis = self.bus.redis
        if redis is None:
            return True
        key, now = presence_key(workspace_id), time.time()
        try:
            async with redis.pipeline(transaction=True) as tx:
                tx.zrangebyscore(key, now, "+inf")
                tx.zadd(key, {self._member(user_id): now + TTL_SECONDS})
                tx.expire(key, TTL_SECONDS * 2)
                live_before, _, _ = await tx.execute()
        except RedisError:
            logger.warning("Presence update failed.", exc_info=True)
            return True
        return not any(_user_of(m) == user_id for m in live_before)

    async def _remove(self, workspace_id: int, user_id: int) -> bool:
        """Withdraw this instance's member. True if that leaves the user
        offline everywhere."""
        redis = self.bus.redis
        if redis is None:
            return True
        key = presence_key(workspace_id)
        try:
            async with redis.pipeline(transaction=True) as tx:
                tx.zrem(key, self._member(user_id))
                tx.zrangebyscore(key, time.time(), "+inf")
                removed, live_after = await tx.execute()
        except RedisError:
            logger.warning("Presence update failed.", exc_info=True)
            return True
        return bool(removed) and not any(_user_of(m) == user_id for m in live_after)

    async def _beat(self) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            try:
                await self._refresh_and_sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Presence heartbeat failed.", exc_info=True)

    async def _refresh_and_sweep(self) -> None:
        redis = self.bus.redis
        now = time.time()
        # Catch anything a missed sync left behind, then keep our members alive.
        for workspace_id in set(self._registered) | set(self.bus.local.connections):
            await self.sync(workspace_id)
        for workspace_id, users in list(self._registered.items()):
            if users:
                key = presence_key(workspace_id)
                await redis.zadd(key, {self._member(u): now + TTL_SECONDS for u in users})
                await redis.expire(key, TTL_SECONDS * 2)

        # Members another instance stopped refreshing (it died). Only workspaces
        # with someone here to see the list matter. ZREM's count decides which
        # instance announces each one, so nobody hears it twice.
        for workspace_id in list(self.bus.local.connections):
            key = presence_key(workspace_id)
            for member in await redis.zrangebyscore(key, "-inf", now):
                async with redis.pipeline(transaction=True) as tx:
                    tx.zrem(key, member)
                    tx.zrangebyscore(key, now, "+inf")
                    removed, live = await tx.execute()
                user_id = _user_of(member)
                if removed and not any(_user_of(m) == user_id for m in live):
                    await self._announce_left(workspace_id, user_id)
