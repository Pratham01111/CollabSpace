"""Presence: who is online, across tabs and across backend instances."""

import asyncio
import time

from app.realtime.bus import EventBus
from app.realtime.manager import ConnectionManager
from app.realtime.presence import TTL_SECONDS, presence_key
from tests.conftest import REDIS_URL, register_and_login
from tests.test_event_bus import FakeSocket, _workspace_ids, needs_redis, started, until


def presence_events(sock: FakeSocket) -> list[tuple[str, int]]:
    return [
        (m["type"], m["user"]["id"])
        for m in sock.received
        if m.get("type") in ("USER_JOINED", "USER_LEFT")
    ]


async def settle():
    await asyncio.sleep(0.25)  # time for anything published to arrive


# ---- across instances (real Redis) -------------------------------------------


@needs_redis
def test_presence_spans_instances_and_counts_each_user_once():
    async def scenario():
        bus1 = EventBus(ConnectionManager(), REDIS_URL)
        bus2 = EventBus(ConnectionManager(), REDIS_URL)
        await started(bus1, bus2)
        try:
            ws = next(_workspace_ids)
            bob = FakeSocket()
            await bus2.join(ws, 2, "bob@example.com", bob)  # Bob on server 2

            alice_tab1 = FakeSocket()
            await bus1.join(ws, 1, "alice@example.com", alice_tab1)  # Alice on server 1
            await until(lambda: presence_events(bob))
            assert presence_events(bob) == [("USER_JOINED", 1)]
            assert [m for m in bob.received if m["type"] == "USER_JOINED"][0]["user"] == {
                "id": 1,
                "email": "alice@example.com",
            }
            # Not announced to herself. (She may still hear Bob's own arrival if
            # it was in flight as she connected; that is harmless, since her
            # snapshot already lists him.)
            await settle()
            assert ("USER_JOINED", 1) not in presence_events(alice_tab1)

            # Both servers agree on who is online.
            assert await bus1.presence.online_user_ids(ws) == [1, 2]
            assert await bus2.presence.online_user_ids(ws) == [1, 2]

            # A second tab, on the other server: still one Alice, no new event.
            alice_tab2 = FakeSocket()
            await bus2.join(ws, 1, "alice@example.com", alice_tab2)
            await settle()
            assert presence_events(bob) == [("USER_JOINED", 1)]
            assert await bus1.presence.online_user_ids(ws) == [1, 2]

            # Closing one tab is not leaving.
            await bus1.leave(ws, 1, alice_tab1)
            await settle()
            assert presence_events(bob) == [("USER_JOINED", 1)]
            assert await bus2.presence.online_user_ids(ws) == [1, 2]

            # Closing the last one is.
            await bus2.leave(ws, 1, alice_tab2)
            await until(lambda: len(presence_events(bob)) == 2)
            assert presence_events(bob) == [("USER_JOINED", 1), ("USER_LEFT", 1)]
            assert await bus1.presence.online_user_ids(ws) == [2]
        finally:
            await bus1.stop()
            await bus2.stop()

    asyncio.run(scenario())


@needs_redis
def test_users_of_a_crashed_instance_are_swept_and_announced_once():
    async def scenario():
        bus1 = EventBus(ConnectionManager(), REDIS_URL)
        bus2 = EventBus(ConnectionManager(), REDIS_URL)
        await started(bus1, bus2)
        try:
            ws = next(_workspace_ids)
            watcher1, watcher2 = FakeSocket(), FakeSocket()
            await bus1.join(ws, 1, "a@example.com", watcher1)
            await bus2.join(ws, 2, "b@example.com", watcher2)

            # A third server had Carol connected, then died without cleaning up:
            # its member is simply left to lapse.
            await bus1.redis.zadd(presence_key(ws), {"3:deadinstance": time.time() - 1})
            assert 3 not in await bus1.presence.online_user_ids(ws)  # expired = offline

            # Both surviving servers sweep; only one may announce it.
            await asyncio.gather(
                bus1.presence._refresh_and_sweep(), bus2.presence._refresh_and_sweep()
            )
            await until(lambda: ("USER_LEFT", 3) in presence_events(watcher1))
            await settle()
            assert presence_events(watcher1).count(("USER_LEFT", 3)) == 1
            assert presence_events(watcher2).count(("USER_LEFT", 3)) == 1
            assert await bus1.redis.zscore(presence_key(ws), "3:deadinstance") is None
        finally:
            await bus1.stop()
            await bus2.stop()

    asyncio.run(scenario())


@needs_redis
def test_heartbeat_keeps_live_members_from_lapsing():
    async def scenario():
        bus = EventBus(ConnectionManager(), REDIS_URL)
        await started(bus)
        try:
            ws = next(_workspace_ids)
            await bus.join(ws, 1, "a@example.com", FakeSocket())
            member = f"1:{bus.presence.instance_id}"
            # Pretend the entry is about to lapse; a heartbeat must push it out.
            await bus.redis.zadd(presence_key(ws), {member: time.time() + 1})
            await bus.presence._refresh_and_sweep()
            assert await bus.redis.zscore(presence_key(ws), member) > time.time() + TTL_SECONDS - 5
        finally:
            await bus.stop()

    asyncio.run(scenario())


@needs_redis
def test_kicked_user_is_announced_as_left():
    async def scenario():
        bus1 = EventBus(ConnectionManager(), REDIS_URL)
        bus2 = EventBus(ConnectionManager(), REDIS_URL)
        await started(bus1, bus2)
        try:
            ws = next(_workspace_ids)
            owner, removed = FakeSocket(), FakeSocket()
            await bus1.join(ws, 1, "owner@example.com", owner)
            await bus2.join(ws, 2, "removed@example.com", removed)
            await until(lambda: presence_events(owner))

            await bus1.disconnect_user(ws, 2, 4404, "Workspace not found.")
            await until(lambda: ("USER_LEFT", 2) in presence_events(owner))
            assert await bus1.presence.online_user_ids(ws) == [1]
        finally:
            await bus1.stop()
            await bus2.stop()

    asyncio.run(scenario())


# ---- through the real WebSocket route (single instance, no Redis) ------------


def test_connect_snapshot_then_live_join_and_leave(client, owner):
    workspace = client.post("/workspaces", json={"name": "W"}, headers=owner).json()
    member = register_and_login(client, "member@example.com")
    client.post(f"/workspaces/{workspace['id']}/members", json={"email": "member@example.com"}, headers=owner)
    url = f"/ws/workspaces/{workspace['id']}?token="
    owner_token = owner["Authorization"].split()[1]
    member_token = member["Authorization"].split()[1]

    with client.websocket_connect(url + owner_token) as owner_ws:
        hello = owner_ws.receive_json()
        assert [u["email"] for u in hello["online_users"]] == ["owner@example.com"]

        with client.websocket_connect(url + member_token) as tab1:
            joined = owner_ws.receive_json()
            assert joined == {
                "type": "USER_JOINED",
                "user": {"id": joined["user"]["id"], "email": "member@example.com"},
            }
            snapshot = tab1.receive_json()["online_users"]
            assert sorted(u["email"] for u in snapshot) == ["member@example.com", "owner@example.com"]

            with client.websocket_connect(url + member_token) as tab2:
                tab2.receive_json()
                # Second tab: no second USER_JOINED. Prove it with a ping, whose
                # pong would otherwise queue behind it.
                owner_ws.send_text("ping")
                assert owner_ws.receive_json() == {"type": "pong"}
            # tab2 closed, tab1 still open: still online, nothing announced.
            owner_ws.send_text("ping")
            assert owner_ws.receive_json() == {"type": "pong"}

        left = owner_ws.receive_json()
        assert left["type"] == "USER_LEFT"
        assert left["user"]["id"] == joined["user"]["id"]
