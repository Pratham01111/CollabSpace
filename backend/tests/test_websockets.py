"""The workspace WebSocket: who may connect, what they receive, and cleanup.

The app under test runs without Redis, so these go through the in-process
connection manager. Cross-instance delivery is in test_event_bus.py, presence
in test_presence.py.
"""

import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.realtime.manager import manager


def ws_url(workspace_id, token=None):
    url = f"/ws/workspaces/{workspace_id}"
    return url if token is None else f"{url}?token={token}"


def connect(client, workspace_id, account):
    """Open a socket and consume the "connected" greeting."""
    ctx = client.websocket_connect(ws_url(workspace_id, account.token))
    ws = ctx.__enter__()
    hello = ws.receive_json()
    assert hello["type"] == "connected", hello
    return ctx, ws


def assert_nothing_pending(ws):
    """Nothing was sent to this socket. A ping's pong would queue behind
    anything already sent, so receiving the pong first proves the queue was empty."""
    ws.send_text("ping")
    assert ws.receive_json() == {"type": "pong"}


def rejected_with(client, url) -> tuple[int, str]:
    with client.websocket_connect(url) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    return closed.value.code, closed.value.reason


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.01)


# ---- connecting ---------------------------------------------------------------


def test_member_connects_and_is_greeted(client, team):
    with client.websocket_connect(ws_url(team.workspace_id, team.member.token)) as ws:
        hello = ws.receive_json()

        assert hello["type"] == "connected"
        assert hello["workspace_id"] == team.workspace_id
        assert hello["user_id"] == team.member.id
        assert_nothing_pending(ws)


def test_connection_is_tracked_by_the_manager(client, team):
    with client.websocket_connect(ws_url(team.workspace_id, team.member.token)) as ws:
        ws.receive_json()
        sockets = manager.connections[team.workspace_id][team.member.id]
        assert len(sockets) == 1


def _token(user_id, *, key=None, expires_in=timedelta(minutes=5)):
    now = datetime.now(UTC)
    return jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + expires_in},
        key or settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


@pytest.mark.parametrize(
    ("make_token", "reason"),
    [
        (lambda user: None, "Not authenticated"),
        (lambda user: "", "Not authenticated"),
        (lambda user: "not-a-jwt", "Could not validate credentials"),
        (lambda user: _token(user.id, key="some-other-secret-that-is-long-enough"), "Could not validate credentials"),
        (lambda user: _token(user.id, expires_in=timedelta(seconds=-1)), "Token has expired"),
        (lambda user: _token(999_999), "User no longer exists"),
    ],
    ids=["missing", "empty", "malformed", "wrong-signature", "expired", "deleted-user"],
)
def test_bad_token_is_closed_with_4401(client, team, make_token, reason):
    code, why = rejected_with(client, ws_url(team.workspace_id, make_token(team.member)))
    assert (code, why) == (4401, reason)
    assert team.workspace_id not in manager.connections


def test_non_member_is_closed_with_4404(client, team):
    assert rejected_with(client, ws_url(team.workspace_id, team.outsider.token)) == (4404, "Workspace not found.")


def test_non_member_and_missing_workspace_look_the_same(client, team):
    someone_elses = rejected_with(client, ws_url(team.workspace_id, team.outsider.token))
    nonexistent = rejected_with(client, ws_url(999_999, team.outsider.token))
    assert someone_elses == nonexistent


# ---- cleanup ------------------------------------------------------------------


def test_disconnect_removes_the_socket_from_the_manager(client, team):
    with client.websocket_connect(ws_url(team.workspace_id, team.member.token)) as ws:
        ws.receive_json()
        assert team.member.id in manager.connections[team.workspace_id]

    wait_until(lambda: team.workspace_id not in manager.connections)


def test_closing_one_tab_keeps_the_other(client, team):
    with client.websocket_connect(ws_url(team.workspace_id, team.member.token)) as tab1:
        tab1.receive_json()
        with client.websocket_connect(ws_url(team.workspace_id, team.member.token)) as tab2:
            tab2.receive_json()
            assert len(manager.connections[team.workspace_id][team.member.id]) == 2

        wait_until(lambda: len(manager.connections[team.workspace_id][team.member.id]) == 1)
        assert_nothing_pending(tab1)  # still alive

    wait_until(lambda: team.workspace_id not in manager.connections)


def test_removed_member_is_disconnected_and_untracked(client, team):
    with client.websocket_connect(ws_url(team.workspace_id, team.member.token)) as ws:
        ws.receive_json()
        client.delete(f"/workspaces/{team.workspace_id}/members/{team.member.id}", headers=team.owner.headers)

        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                ws.receive_json()
        assert closed.value.code == 4404

    wait_until(lambda: team.workspace_id not in manager.connections)


# ---- events ---------------------------------------------------------------------


def test_patch_broadcasts_task_updated(client, team, team_task):
    ctx, ws = connect(client, team.workspace_id, team.member)
    try:
        response = client.patch(
            f"/tasks/{team_task['id']}",
            json={"status": "DONE", "expected_version": 1},
            headers=team.owner.headers,
        )
        event = ws.receive_json()

        assert event == {"type": "TASK_UPDATED", "task": response.json()}
        assert event["task"]["status"] == "DONE"
        assert event["task"]["version"] == 2
    finally:
        ctx.__exit__(None, None, None)


def test_create_and_delete_are_broadcast(client, team):
    ctx, ws = connect(client, team.workspace_id, team.member)
    try:
        created = client.post(
            f"/workspaces/{team.workspace_id}/tasks", json={"title": "new"}, headers=team.owner.headers
        ).json()
        assert ws.receive_json() == {"type": "TASK_CREATED", "task": created}

        client.delete(f"/tasks/{created['id']}", headers=team.owner.headers)
        deleted = ws.receive_json()
        assert deleted["type"] == "TASK_DELETED"
        assert deleted["task"]["id"] == created["id"]
    finally:
        ctx.__exit__(None, None, None)


def test_comment_is_broadcast(client, team, team_task):
    ctx, ws = connect(client, team.workspace_id, team.member)
    try:
        comment = client.post(
            f"/tasks/{team_task['id']}/comments", json={"body": "hi"}, headers=team.owner.headers
        ).json()
        assert ws.receive_json() == {"type": "COMMENT_CREATED", "comment": comment}
    finally:
        ctx.__exit__(None, None, None)


def test_sender_and_every_tab_receive_the_event(client, team, team_task):
    owner_ctx, owner_ws = connect(client, team.workspace_id, team.owner)
    tab1_ctx, tab1 = connect(client, team.workspace_id, team.member)
    tab2_ctx, tab2 = connect(client, team.workspace_id, team.member)
    try:
        # Each new connection announces the user to those already connected;
        # clear those out of the way first.
        owner_ws.receive_json()  # member joined (once, despite two tabs)
        assert_nothing_pending(owner_ws)

        client.patch(
            f"/tasks/{team_task['id']}", json={"title": "x", "expected_version": 1}, headers=team.owner.headers
        )
        for ws in (owner_ws, tab1, tab2):
            assert ws.receive_json()["type"] == "TASK_UPDATED"
    finally:
        for ctx in (tab2_ctx, tab1_ctx, owner_ctx):
            ctx.__exit__(None, None, None)


def test_broadcast_stays_within_its_workspace(client, team, team_task, make_account):
    other = make_account("elsewhere")
    other_ws_id = client.post("/workspaces", json={"name": "Elsewhere"}, headers=other.headers).json()["id"]

    here_ctx, here = connect(client, team.workspace_id, team.member)
    there_ctx, there = connect(client, other_ws_id, other)
    try:
        client.patch(
            f"/tasks/{team_task['id']}", json={"title": "x", "expected_version": 1}, headers=team.owner.headers
        )
        client.post(f"/tasks/{team_task['id']}/comments", json={"body": "hi"}, headers=team.owner.headers)

        assert here.receive_json()["type"] == "TASK_UPDATED"
        assert here.receive_json()["type"] == "COMMENT_CREATED"
        assert_nothing_pending(there)
    finally:
        there_ctx.__exit__(None, None, None)
        here_ctx.__exit__(None, None, None)


def test_rejected_requests_broadcast_nothing(client, team, team_task):
    ctx, ws = connect(client, team.workspace_id, team.member)
    try:
        task_url = f"/tasks/{team_task['id']}"
        client.patch(task_url, json={"title": "", "expected_version": 1}, headers=team.owner.headers)  # 422
        client.patch(task_url, json={"title": "x", "expected_version": 9}, headers=team.owner.headers)  # 409
        client.patch(task_url, json={"title": "x", "expected_version": 1}, headers=team.outsider.headers)  # 404
        client.patch(task_url, json={"expected_version": 1}, headers=team.owner.headers)  # no-op
        client.post(f"{task_url}/comments", json={"body": " "}, headers=team.owner.headers)  # 422

        assert_nothing_pending(ws)
    finally:
        ctx.__exit__(None, None, None)
