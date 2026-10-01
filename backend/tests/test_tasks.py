"""Tasks: create, read, update, delete, and what the API refuses.

Version conflicts are in test_task_concurrency.py; access rules in
test_authorization.py.
"""

import pytest


def tasks_url(team):
    return f"/workspaces/{team.workspace_id}/tasks"


def create(client, team, account=None, **body):
    return client.post(tasks_url(team), json=body, headers=(account or team.member).headers)


def board(client, team):
    return client.get(tasks_url(team), headers=team.owner.headers).json()


# ---- create ---------------------------------------------------------------------


def test_create_task_with_defaults(client, team):
    response = create(client, team, title="  Write tests  ")

    assert response.status_code == 201
    task = response.json()
    assert task["title"] == "Write tests"  # trimmed
    assert task["description"] is None
    assert task["status"] == "TODO"
    assert task["version"] == 1
    assert task["workspace_id"] == team.workspace_id
    # The author comes from the token, not the body.
    assert task["created_by"] == team.member.id
    assert task["created_at"] and task["updated_at"]


def test_create_task_with_every_field(client, team):
    task = create(client, team, title="Ship", description="Friday", status="IN_PROGRESS", position=5.5).json()
    assert (task["description"], task["status"], task["position"]) == ("Friday", "IN_PROGRESS", 5.5)


def test_new_tasks_append_to_the_bottom_of_their_own_column(client, team):
    a = create(client, team, title="a").json()
    b = create(client, team, title="b").json()
    c = create(client, team, title="c", status="DONE").json()

    assert a["position"] < b["position"]
    assert c["position"] == 1.0  # columns are numbered independently


def test_list_is_in_board_order(client, team):
    for title, status in [("d1", "DONE"), ("t1", "TODO"), ("p1", "IN_PROGRESS"), ("t2", "TODO")]:
        create(client, team, title=title, status=status)

    assert [t["title"] for t in board(client, team)] == ["t1", "t2", "p1", "d1"]


@pytest.mark.parametrize(
    "body",
    [
        {},  # title is required
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 256},
        {"title": "ok", "status": "BLOCKED"},
        {"title": "ok", "status": "todo"},  # case matters
        {"title": "ok", "position": "first"},
        {"title": None},
    ],
)
def test_create_rejects_invalid_task(client, team, body):
    assert client.post(tasks_url(team), json=body, headers=team.member.headers).status_code == 422
    assert board(client, team) == []


@pytest.mark.parametrize("field", ["created_by", "version", "workspace_id", "id", "created_at"])
def test_create_rejects_server_owned_fields(client, team, field):
    response = client.post(tasks_url(team), json={"title": "ok", field: 1}, headers=team.member.headers)
    assert response.status_code == 422


# ---- update ---------------------------------------------------------------------


def patch(client, account, task, **changes):
    changes.setdefault("expected_version", task["version"])
    return client.patch(f"/tasks/{task['id']}", json=changes, headers=account.headers)


def test_update_task(client, team, team_task):
    response = patch(client, team.member, team_task, title="Renamed", description="Now with detail")

    assert response.status_code == 200
    task = response.json()
    assert (task["title"], task["description"], task["version"]) == ("Renamed", "Now with detail", 2)
    assert task["created_by"] == team.owner.id  # unchanged by someone else's edit
    assert task["updated_at"] >= team_task["updated_at"]
    assert board(client, team)[0]["title"] == "Renamed"


def test_update_only_changes_what_is_sent(client, team, team_task):
    patch(client, team.owner, team_task, description="keep me")
    current = board(client, team)[0]

    patch(client, team.owner, current, title="New title")

    assert board(client, team)[0]["description"] == "keep me"


def test_update_null_description_clears_it(client, team, team_task):
    first = patch(client, team.owner, team_task, description="temporary").json()
    assert patch(client, team.owner, first, description=None).json()["description"] is None


def test_moving_to_another_column_lands_at_its_bottom(client, team, team_task):
    done = create(client, team, title="already done", status="DONE").json()

    moved = patch(client, team.owner, team_task, status="DONE").json()

    assert moved["status"] == "DONE"
    assert moved["position"] > done["position"]


def test_empty_update_changes_nothing(client, team, team_task):
    response = patch(client, team.owner, team_task)
    assert response.status_code == 200
    assert response.json()["version"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "BLOCKED"},
        {"title": ""},
        {"title": "   "},
        {"title": None},
        {"status": None},
        {"position": None},
        {"version": 7},
        {"created_by": 1},
        {"workspace_id": 2},
    ],
)
def test_update_rejects_invalid_changes(client, team, team_task, changes):
    assert patch(client, team.owner, team_task, **changes).status_code == 422
    assert board(client, team)[0] == team_task


def test_update_missing_task_is_404(client, team):
    response = client.patch("/tasks/999999", json={"title": "x", "expected_version": 1}, headers=team.owner.headers)
    assert response.status_code == 404


# ---- delete ---------------------------------------------------------------------


def test_delete_task(client, team, team_task):
    keep = create(client, team, title="keep").json()

    response = client.delete(f"/tasks/{team_task['id']}", headers=team.member.headers)

    assert response.status_code == 204
    assert response.content == b""
    assert [t["id"] for t in board(client, team)] == [keep["id"]]


def test_deleted_task_is_gone_everywhere(client, team, team_task):
    client.post(f"/tasks/{team_task['id']}/comments", json={"body": "hi"}, headers=team.owner.headers)
    client.delete(f"/tasks/{team_task['id']}", headers=team.owner.headers)

    assert client.delete(f"/tasks/{team_task['id']}", headers=team.owner.headers).status_code == 404
    assert patch(client, team.owner, team_task, title="ghost").status_code == 404
    assert client.get(f"/tasks/{team_task['id']}/comments", headers=team.owner.headers).status_code == 404


def test_tasks_survive_their_author_leaving(client, team):
    task = create(client, team, account=team.member, title="mine").json()
    client.delete(f"/workspaces/{team.workspace_id}/members/me", headers=team.member.headers)

    remaining = board(client, team)
    assert [(t["id"], t["created_by"]) for t in remaining] == [(task["id"], team.member.id)]


# ---- outsiders ------------------------------------------------------------------


def test_outsider_cannot_list_create_update_or_delete(client, team, team_task):
    outsider = team.outsider.headers
    assert client.get(tasks_url(team), headers=outsider).status_code == 404
    assert client.post(tasks_url(team), json={"title": "x"}, headers=outsider).status_code == 404
    assert patch(client, team.outsider, team_task, title="x").status_code == 404
    assert client.delete(f"/tasks/{team_task['id']}", headers=outsider).status_code == 404
    assert board(client, team) == [team_task]


def test_member_of_another_workspace_cannot_reach_this_ones_tasks(client, team, team_task):
    """Being a member *somewhere* is not enough; it has to be this workspace."""
    client.post("/workspaces", json={"name": "Outsider's own"}, headers=team.outsider.headers)
    assert patch(client, team.outsider, team_task, title="x").status_code == 404
