"""Phase 11: events reach sockets on every backend instance via Redis.

Each test builds two EventBus instances in one process, each with its own
ConnectionManager: as far as Redis can tell, two separate servers.
"""

import asyncio
import itertools
import uuid

import pytest
from redis.asyncio import Redis
from starlette.websockets import WebSocketState

from app.realtime.bus import CLOSE_SERVICE_RESTART, EventBus
from app.realtime.manager import ConnectionManager
from tests.conftest import REDIS_URL

# Unique per test, so a dev server subscribed to the same Redis is never
# handed a socket's worth of anything it cares about.
_workspace_ids = itertools.count(900_000_000 + uuid.uuid4().int % 1_000_000)


class FakeSocket:
    def __init__(self):
        self.application_state = WebSocketState.CONNECTED
        self.received: list = []
        self.closed_with: int | None = None

    async def send_json(self, message):
        self.received.append(message)

    async def close(self, code, reason):
        self.closed_with = code
        self.application_state = WebSocketState.DISCONNECTED


def redis_available() -> bool:
    async def ping():
        client = Redis.from_url(REDIS_URL)
        try:
            return await client.ping()
        finally:
            await client.aclose()

    try:
        return bool(REDIS_URL) and asyncio.run(ping())
    except Exception:
        return False


needs_redis = pytest.mark.skipif(not redis_available(), reason="Redis is not running")


async def started(*buses: EventBus) -> None:
    for b in buses:
        await b.start()
    await asyncio.wait_for(asyncio.gather(*(b.subscribed.wait() for b in buses)), 5)


async def until(predicate, timeout=3.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


@needs_redis
def test_event_from_one_instance_reaches_a_socket_on_another():
    async def scenario():
        server1, server2 = ConnectionManager(), ConnectionManager()
        bus1, bus2 = EventBus(server1, REDIS_URL), EventBus(server2, REDIS_URL)
        await started(bus1, bus2)
        try:
            workspace = next(_workspace_ids)
            alice, bob = FakeSocket(), FakeSocket()
            await server1.connect(workspace, 1, alice)  # Alice on server 1
            await server2.connect(workspace, 2, bob)  # Bob on server 2

            event = {"type": "TASK_UPDATED", "task": {"id": 42, "version": 3}}
            await bus1.broadcast(workspace, event)  # the edit lands on server 1

            await until(lambda: bob.received and alice.received)
            await asyncio.sleep(0.2)  # long enough for any duplicate to show up
            assert bob.received == [event]
            # The publisher hears it through its own subscription, exactly once.
            assert alice.received == [event]
        finally:
            await bus1.stop()
            await bus2.stop()

    asyncio.run(scenario())


@needs_redis
def test_other_workspaces_hear_nothing():
    async def scenario():
        server1, server2 = ConnectionManager(), ConnectionManager()
        bus1, bus2 = EventBus(server1, REDIS_URL), EventBus(server2, REDIS_URL)
        await started(bus1, bus2)
        try:
            here, elsewhere = next(_workspace_ids), next(_workspace_ids)
            bystander = FakeSocket()
            await server2.connect(elsewhere, 2, bystander)
            await bus1.broadcast(here, {"type": "TASK_CREATED", "task": {"id": 1}})
            await asyncio.sleep(0.3)
            assert bystander.received == []
        finally:
            await bus1.stop()
            await bus2.stop()

    asyncio.run(scenario())


@needs_redis
def test_removed_member_is_disconnected_on_every_instance():
    async def scenario():
        server1, server2 = ConnectionManager(), ConnectionManager()
        bus1, bus2 = EventBus(server1, REDIS_URL), EventBus(server2, REDIS_URL)
        await started(bus1, bus2)
        try:
            workspace = next(_workspace_ids)
            tab_on_1, tab_on_2, other_user = FakeSocket(), FakeSocket(), FakeSocket()
            await server1.connect(workspace, 7, tab_on_1)
            await server2.connect(workspace, 7, tab_on_2)
            await server2.connect(workspace, 8, other_user)

            await bus1.disconnect_user(workspace, 7, 4404, "Workspace not found.")

            await until(lambda: tab_on_1.closed_with and tab_on_2.closed_with)
            assert (tab_on_1.closed_with, tab_on_2.closed_with) == (4404, 4404)
            assert server2.connected_user_ids(workspace) == [8]
            assert other_user.closed_with is None
        finally:
            await bus1.stop()
            await bus2.stop()

    asyncio.run(scenario())


@needs_redis
def test_lost_subscription_resets_local_sockets_so_clients_resync():
    """Events published while an instance was unsubscribed are gone. Once it
    resubscribes it closes its sockets with 1012, and clients reconnect and
    re-read from Postgres."""

    async def scenario():
        local = ConnectionManager()
        name = f"collabspace-test-{uuid.uuid4().hex[:8]}"
        bus = EventBus(local, REDIS_URL, client_name=name)
        await started(bus)
        admin = Redis.from_url(REDIS_URL, decode_responses=True)
        try:
            workspace = next(_workspace_ids)
            sock = FakeSocket()
            await local.connect(workspace, 1, sock)

            # Cut only this bus's subscriber connection.
            for client in await admin.client_list():
                if client["name"] == name and int(client.get("psub", 0)) > 0:
                    await admin.client_kill_filter(_id=client["id"])

            await until(lambda: sock.closed_with is not None, timeout=5)
            assert sock.closed_with == CLOSE_SERVICE_RESTART
            await asyncio.wait_for(bus.subscribed.wait(), 5)

            # And it is listening again.
            fresh = FakeSocket()
            await local.connect(workspace, 2, fresh)
            await bus.broadcast(workspace, {"type": "TASK_CREATED", "task": {"id": 1}})
            await until(lambda: fresh.received)
        finally:
            await admin.aclose()
            await bus.stop()

    asyncio.run(scenario())


def test_without_redis_events_still_reach_local_sockets():
    async def scenario():
        local = ConnectionManager()
        bus = EventBus(local, None)
        await bus.start()
        sock = FakeSocket()
        await local.connect(1, 1, sock)
        await bus.broadcast(1, {"type": "TASK_CREATED", "task": {"id": 1}})
        assert sock.received == [{"type": "TASK_CREATED", "task": {"id": 1}}]
        await bus.stop()

    asyncio.run(scenario())


def test_unreachable_redis_falls_back_to_local_delivery():
    async def scenario():
        local = ConnectionManager()
        bus = EventBus(local, "redis://localhost:1/0")  # nothing listens there
        await bus.start()
        try:
            sock = FakeSocket()
            await local.connect(1, 1, sock)
            await bus.broadcast(1, {"type": "TASK_CREATED", "task": {"id": 1}})
            assert sock.received == [{"type": "TASK_CREATED", "task": {"id": 1}}]
        finally:
            await bus.stop()

    asyncio.run(scenario())
