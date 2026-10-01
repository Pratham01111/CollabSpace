"""Phase 10: every task update is checked against the version the client saw."""

import threading

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.database.models import Task
from app.main import app
from app.tasks import service
from tests.conftest import register_and_login


def stored(client, headers, task):
    """The task as the API returns it now."""
    tasks = client.get(f"/workspaces/{task['workspace_id']}/tasks", headers=headers).json()
    return next(t for t in tasks if t["id"] == task["id"])


def add_member(client, owner, task):
    member = register_and_login(client, "member@example.com")
    client.post(
        f"/workspaces/{task['workspace_id']}/members", json={"email": "member@example.com"}, headers=owner
    )
    return member


def test_update_with_current_version_applies_and_increments(client, owner, task):
    assert task["version"] == 1

    response = client.patch(
        f"/tasks/{task['id']}", json={"title": "Renamed", "expected_version": 1}, headers=owner
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Renamed"
    assert body["version"] == 2
    assert stored(client, owner, task)["version"] == 2

    # And the new version is what the next edit must quote.
    again = client.patch(
        f"/tasks/{task['id']}", json={"status": "DONE", "expected_version": 2}, headers=owner
    )
    assert again.status_code == 200
    assert again.json()["version"] == 3


def test_update_with_stale_version_is_409_and_changes_nothing(client, owner, task):
    client.patch(f"/tasks/{task['id']}", json={"title": "First edit", "expected_version": 1}, headers=owner)

    stale = client.patch(
        f"/tasks/{task['id']}",
        json={"title": "Based on old data", "status": "DONE", "expected_version": 1},
        headers=owner,
    )

    assert stale.status_code == 409
    body = stale.json()
    assert body["detail"] == "This task was updated by someone else."
    # The client is handed the task as it actually is now.
    assert body["current_task"]["title"] == "First edit"
    assert body["current_task"]["version"] == 2

    current = stored(client, owner, task)
    assert (current["title"], current["status"], current["version"]) == ("First edit", "TODO", 2)


def test_future_version_is_also_a_conflict(client, owner, task):
    response = client.patch(
        f"/tasks/{task['id']}", json={"title": "x", "expected_version": 99}, headers=owner
    )
    assert response.status_code == 409
    assert stored(client, owner, task)["title"] == "Original"


@pytest.mark.parametrize("payload", [{"title": "No version"}, {"title": "x", "expected_version": 0}])
def test_expected_version_is_required_and_positive(client, owner, task, payload):
    assert client.patch(f"/tasks/{task['id']}", json=payload, headers=owner).status_code == 422


def test_second_of_two_edits_from_the_same_version_conflicts(client, owner, task):
    """Two people open version 1; whoever saves second is told, not overwritten."""
    member = add_member(client, owner, task)

    first = client.patch(
        f"/tasks/{task['id']}", json={"title": "Alice's title", "expected_version": 1}, headers=owner
    )
    second = client.patch(
        f"/tasks/{task['id']}", json={"title": "Bob's title", "expected_version": 1}, headers=member
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["current_task"]["title"] == "Alice's title"
    assert stored(client, owner, task)["title"] == "Alice's title"


def test_race_after_version_check_still_conflicts(task):
    """The window the fast-path check cannot close: both requests have loaded
    version 1 and passed the in-memory comparison before either writes. The
    conditional UPDATE must still let only one through."""
    with SessionLocal() as alice_db, SessionLocal() as bob_db:
        alice_task = alice_db.get(Task, task["id"])
        bob_task = bob_db.get(Task, task["id"])
        assert alice_task.version == bob_task.version == 1

        service.update_task(alice_db, alice_task, {"title": "Alice"}, expected_version=1)

        # Bob's session still holds version 1 in memory, so his fast-path check
        # passes; only the version test inside the UPDATE catches him.
        assert bob_task.version == 1
        with pytest.raises(service.VersionConflictError) as conflict:
            service.update_task(bob_db, bob_task, {"title": "Bob"}, expected_version=1)

        assert conflict.value.current.title == "Alice"
        assert conflict.value.current.version == 2

    with SessionLocal() as db:
        row = db.get(Task, task["id"])
        assert (row.title, row.version) == ("Alice", 2)


def test_truly_concurrent_requests_exactly_one_wins(client, owner, task):
    """Many simultaneous PATCHes quoting the same version, from separate
    threads: exactly one applies, every other one is a 409, no lost update."""
    attempts = 8
    barrier = threading.Barrier(attempts)
    results: list[tuple[int, str]] = []
    lock = threading.Lock()

    def attempt(n: int) -> None:
        with TestClient(app) as c:
            barrier.wait()
            r = c.patch(
                f"/tasks/{task['id']}", json={"title": f"writer {n}", "expected_version": 1}, headers=owner
            )
        with lock:
            results.append((r.status_code, f"writer {n}"))

    threads = [threading.Thread(target=attempt, args=(n,)) for n in range(attempts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    codes = sorted(code for code, _ in results)
    assert codes == [200] + [409] * (attempts - 1)

    winner = next(title for code, title in results if code == 200)
    current = stored(client, owner, task)
    assert (current["title"], current["version"]) == (winner, 2)


def test_conflict_is_not_broadcast(client, owner, task):
    with client.websocket_connect(
        f"/ws/workspaces/{task['workspace_id']}?token={owner['Authorization'].split()[1]}"
    ) as ws:
        assert ws.receive_json()["type"] == "connected"

        client.patch(f"/tasks/{task['id']}", json={"title": "A", "expected_version": 1}, headers=owner)
        client.patch(f"/tasks/{task['id']}", json={"title": "B", "expected_version": 1}, headers=owner)
        client.patch(f"/tasks/{task['id']}", json={"title": "C", "expected_version": 2}, headers=owner)

        # Two successful updates, two events; the 409 in between sent nothing.
        titles = [ws.receive_json()["task"]["title"] for _ in range(2)]
        assert titles == ["A", "C"]
