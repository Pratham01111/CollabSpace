"""Production hardening: one error shape, input bounds, failure handling, logs."""

import logging
import time

import pytest
from sqlalchemy.exc import OperationalError
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.database import engine
from app.validation import MAX_ID
from app.workspaces import service as workspace_service

ERROR_KEYS = {"detail", "code", "request_id"}


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert ERROR_KEYS <= set(body), body
    assert isinstance(body["detail"], str) and body["detail"]
    assert body["code"] == code
    # The id in the body is the one in the header, for matching up with logs.
    assert body["request_id"] == response.headers["x-request-id"]
    return body


# ---- one shape for every error ----------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "status", "code"),
    [
        ("GET", "/no-such-route", 404, "not_found"),
        ("PUT", "/health", 405, "method_not_allowed"),
        ("GET", "/auth/me", 401, "unauthorized"),
    ],
)
def test_framework_errors_use_the_shared_shape(client, method, path, status, code):
    assert_error(client.request(method, path), status, code)


def test_401_keeps_its_www_authenticate_header(client):
    assert client.get("/auth/me").headers["www-authenticate"] == "Bearer"


def test_route_errors_use_the_shared_shape(client, team, make_account):
    newcomer = make_account("newcomer")
    add = lambda account, role: client.post(  # noqa: E731
        f"/workspaces/{team.workspace_id}/members",
        json={"user_id": newcomer.id, "role": role},
        headers=account.headers,
    )
    assert_error(add(team.admin, "OWNER"), 403, "forbidden")
    assert_error(client.get("/workspaces/424242", headers=team.owner.headers), 404, "not_found")
    add(team.owner, "MEMBER")
    assert_error(add(team.owner, "MEMBER"), 409, "conflict")


def test_validation_error_lists_fields_without_echoing_input(client):
    response = client.post("/auth/register", json={"email": "not-an-email", "password": "hunter2"})

    body = assert_error(response, 422, "validation_error")
    assert {e["field"] for e in body["errors"]} == {"email", "password"}
    assert all(set(e) == {"field", "message"} for e in body["errors"])
    # The rejected password is never sent back.
    assert "hunter2" not in response.text
    assert "input" not in response.text


def test_malformed_json_is_a_clean_422(client, team):
    response = client.post(
        "/workspaces",
        content=b'{"name": ',
        headers={**team.owner.headers, "Content-Type": "application/json"},
    )
    assert_error(response, 422, "validation_error")


def test_version_conflict_has_the_shared_shape_plus_current_task(client, team, team_task):
    url = f"/tasks/{team_task['id']}"
    client.patch(url, json={"title": "first", "expected_version": 1}, headers=team.owner.headers)

    body = assert_error(
        client.patch(url, json={"title": "stale", "expected_version": 1}, headers=team.member.headers),
        409,
        "version_conflict",
    )
    assert body["current_task"]["title"] == "first"


def test_request_id_is_generated_or_taken_from_a_sane_header(client):
    generated = client.get("/health")
    assert len(generated.headers["x-request-id"]) >= 8

    assert client.get("/health", headers={"X-Request-ID": "trace-abc_123"}).headers["x-request-id"] == "trace-abc_123"
    # A header that could be used to inject into logs is replaced, not trusted.
    replaced = client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"}).headers["x-request-id"]
    assert replaced != "bad id\nwith newline" and "\n" not in replaced


# ---- input that used to reach the database --------------------------------------------


@pytest.mark.parametrize("too_big", [MAX_ID + 1, 2**63, 10**30])
def test_out_of_range_ids_are_422_not_500(client, team, too_big):
    h = team.owner.headers
    ws = team.workspace_id
    for response in (
        client.get(f"/workspaces/{too_big}", headers=h),
        client.get(f"/workspaces/{too_big}/tasks", headers=h),
        client.delete(f"/tasks/{too_big}", headers=h),
        client.get(f"/tasks/{too_big}/comments", headers=h),
        client.delete(f"/workspaces/{ws}/members/{too_big}", headers=h),
        client.post(f"/workspaces/{ws}/members", json={"user_id": too_big}, headers=h),
    ):
        assert_error(response, 422, "validation_error")


def test_out_of_range_expected_version_is_422(client, team, team_task):
    response = client.patch(
        f"/tasks/{team_task['id']}", json={"title": "x", "expected_version": 2**40}, headers=team.owner.headers
    )
    assert_error(response, 422, "validation_error")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_non_finite_position_is_rejected_and_the_board_survives(client, team, team_task, value):
    """These parse as JSON floats. Once stored, a NaN position used to make
    every later read of the board fail."""
    headers = {**team.owner.headers, "Content-Type": "application/json"}
    created = client.post(
        f"/workspaces/{team.workspace_id}/tasks", content=f'{{"title": "t", "position": {value}}}', headers=headers
    )
    updated = client.patch(
        f"/tasks/{team_task['id']}", content=f'{{"position": {value}, "expected_version": 1}}', headers=headers
    )

    assert_error(created, 422, "validation_error")
    assert_error(updated, 422, "validation_error")
    board = client.get(f"/workspaces/{team.workspace_id}/tasks", headers=team.owner.headers)
    assert board.status_code == 200
    assert [t["id"] for t in board.json()] == [team_task["id"]]


def test_description_length_is_bounded(client, team):
    url = f"/workspaces/{team.workspace_id}/tasks"
    at_limit = client.post(url, json={"title": "t", "description": "x" * 10_000}, headers=team.owner.headers)
    assert at_limit.status_code == 201
    assert_error(
        client.post(url, json={"title": "t", "description": "x" * 10_001}, headers=team.owner.headers),
        422,
        "validation_error",
    )


# ---- failures stay contained ------------------------------------------------------------


def test_unexpected_exception_is_a_generic_500_without_internals(client, team, monkeypatch, caplog):
    def explode(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(workspace_service, "list_memberships_for_user", explode)

    with caplog.at_level(logging.ERROR, logger="app.request"):
        response = client.get("/workspaces", headers=team.owner.headers)

    body = assert_error(response, 500, "internal_error")
    assert "secret internal detail" not in response.text
    assert "Traceback" not in response.text
    # ...but it is in the log, under the same request id.
    logged = [r for r in caplog.records if getattr(r, "event", None) == "request.error"]
    assert logged and logged[0].exc_info[1].args == ("secret internal detail",)


def test_lost_database_is_a_503_and_the_app_keeps_serving(client, team, monkeypatch):
    def db_down(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, ConnectionRefusedError("connection refused"))

    monkeypatch.setattr(workspace_service, "list_memberships_for_user", db_down)
    assert_error(client.get("/workspaces", headers=team.owner.headers), 503, "database_unavailable")

    monkeypatch.undo()
    assert client.get("/workspaces", headers=team.owner.headers).status_code == 200


def test_pool_is_configured_from_settings():
    assert engine.pool.size() == settings.db_pool_size
    assert engine.pool._max_overflow == settings.db_max_overflow
    assert engine.pool._pre_ping is True


# ---- WebSocket edge cases ---------------------------------------------------------------------


def test_binary_frames_are_ignored_not_fatal(client, team):
    with client.websocket_connect(f"/ws/workspaces/{team.workspace_id}?token={team.member.token}") as ws:
        ws.receive_json()
        ws.send_bytes(b"\x00\x01binary")
        ws.send_text("not a ping")
        ws.send_text("ping")
        assert ws.receive_json() == {"type": "pong"}


def test_out_of_range_workspace_socket_is_4404(client, team):
    with client.websocket_connect(f"/ws/workspaces/{2**63}?token={team.member.token}") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 4404


def test_socket_auth_during_db_outage_says_try_again(client, team, monkeypatch):
    def db_down(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, ConnectionRefusedError("connection refused"))

    monkeypatch.setattr(workspace_service, "get_membership", db_down)
    with client.websocket_connect(f"/ws/workspaces/{team.workspace_id}?token={team.member.token}") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    # 1013 is not 4401/4404, so the client keeps retrying with backoff.
    assert closed.value.code == 1013


# ---- logs ----------------------------------------------------------------------------------------


def events(caplog, name):
    return [r for r in caplog.records if getattr(r, "event", None) == name]


def server_log(caplog) -> str:
    """What the server logged. The test client's own HTTP library (httpx) logs
    every URL it requests; that is not the server's output."""
    server = [r for r in caplog.records if r.name.startswith(("app", "uvicorn"))]
    return "\n".join(f"{r.getMessage()} {vars(r)}" for r in server)


def test_failed_login_is_logged_without_the_password(client, make_account, caplog):
    make_account("alice")
    with caplog.at_level(logging.INFO):
        client.post("/auth/login", json={"email": "alice@example.com", "password": "wrong-password-xyz"})

    [failed] = events(caplog, "auth.login_failed")
    assert failed.email == "alice@example.com"
    assert "wrong-password-xyz" not in caplog.text  # not anywhere, client included


def test_requests_are_logged_with_status_and_timing_but_no_query_string(client, team, caplog):
    with caplog.at_level(logging.INFO):
        client.get(f"/workspaces?token={team.owner.token}", headers=team.owner.headers)

    [line] = [r for r in events(caplog, "request") if r.path == "/workspaces"]
    assert (line.method, line.status) == ("GET", 200)
    assert line.duration_ms >= 0
    assert team.owner.token not in server_log(caplog)


def test_socket_lifecycle_is_logged(client, team, caplog):
    with caplog.at_level(logging.INFO):
        with client.websocket_connect(f"/ws/workspaces/{team.workspace_id}?token={team.member.token}") as ws:
            ws.receive_json()
        with client.websocket_connect(f"/ws/workspaces/{team.workspace_id}?token={team.outsider.token}") as ws:
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()

    deadline = time.monotonic() + 1
    while not events(caplog, "ws.disconnected") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert events(caplog, "ws.connected")[0].user_id == team.member.id
    assert events(caplog, "ws.disconnected")[0].user_id == team.member.id
    assert events(caplog, "ws.rejected")[0].code == 4404
    assert team.member.token not in server_log(caplog)
