"""Authorization: who may touch what.

Two rules run through all of it:

- Someone outside a workspace gets **404, never 403**, for the workspace and
  everything in it. A 403 would confirm that the thing exists.
- Within a workspace, roles decide who manages membership. The caller is
  already a member, so a 403 there gives nothing away.
"""

import pytest

from tests.conftest import Team

# ---- every endpoint, as an outsider ----------------------------------------------

# (method, path template, body). {ws} and {task} are filled from the team.
SCOPED_ENDPOINTS = [
    ("GET", "/workspaces/{ws}", None),
    ("POST", "/workspaces/{ws}/members", {"email": "someone@example.com"}),
    ("DELETE", "/workspaces/{ws}/members/{owner}", None),
    ("DELETE", "/workspaces/{ws}/members/me", None),
    ("GET", "/workspaces/{ws}/tasks", None),
    ("POST", "/workspaces/{ws}/tasks", {"title": "Sneaky"}),
    ("PATCH", "/tasks/{task}", {"title": "Sneaky", "expected_version": 1}),
    ("DELETE", "/tasks/{task}", None),
    ("GET", "/tasks/{task}/comments", None),
    ("POST", "/tasks/{task}/comments", {"body": "Sneaky"}),
]


def _fill(path: str, team: Team, task: dict) -> str:
    return path.format(ws=team.workspace_id, task=task["id"], owner=team.owner.id)


@pytest.mark.parametrize(("method", "path", "body"), SCOPED_ENDPOINTS)
def test_outsider_gets_404_everywhere(client, team, team_task, method, path, body):
    response = client.request(
        method, _fill(path, team, team_task), json=body, headers=team.outsider.headers
    )
    assert response.status_code == 404, response.text


@pytest.mark.parametrize(("method", "path", "body"), SCOPED_ENDPOINTS)
def test_outsider_cannot_tell_real_from_missing(client, team, team_task, method, path, body):
    """Someone else's workspace and one that does not exist look identical."""
    real = client.request(method, _fill(path, team, team_task), json=body, headers=team.outsider.headers)
    missing = client.request(
        method,
        path.format(ws=999_999, task=999_999, owner=team.owner.id),
        json=body,
        headers=team.outsider.headers,
    )
    assert (real.status_code, real.json()) == (missing.status_code, missing.json())


def test_outsider_attempts_change_nothing(client, team, team_task):
    for method, path, body in SCOPED_ENDPOINTS:
        client.request(method, _fill(path, team, team_task), json=body, headers=team.outsider.headers)

    detail = client.get(f"/workspaces/{team.workspace_id}", headers=team.owner.headers).json()
    tasks = client.get(f"/workspaces/{team.workspace_id}/tasks", headers=team.owner.headers).json()
    comments = client.get(f"/tasks/{team_task['id']}/comments", headers=team.owner.headers).json()
    assert len(detail["members"]) == 3
    assert [(t["id"], t["title"], t["version"]) for t in tasks] == [(team_task["id"], "Team task", 1)]
    assert comments == []


def test_outsider_does_not_see_the_workspace_listed(client, team):
    assert client.get("/workspaces", headers=team.outsider.headers).json() == []


# ---- members can use the workspace ------------------------------------------------


@pytest.mark.parametrize("role", ["owner", "admin", "member"])
def test_every_role_can_use_the_workspace(client, team, team_task, role):
    account = getattr(team, role)
    ws, task_id = team.workspace_id, team_task["id"]

    assert client.get(f"/workspaces/{ws}", headers=account.headers).status_code == 200
    assert client.get(f"/workspaces/{ws}/tasks", headers=account.headers).status_code == 200
    created = client.post(f"/workspaces/{ws}/tasks", json={"title": role}, headers=account.headers)
    assert created.status_code == 201
    # Any member may edit any task, not just their own.
    current = client.get(f"/workspaces/{ws}/tasks", headers=account.headers).json()
    version = next(t["version"] for t in current if t["id"] == task_id)
    edited = client.patch(
        f"/tasks/{task_id}", json={"title": f"by {role}", "expected_version": version}, headers=account.headers
    )
    assert edited.status_code == 200
    assert client.post(f"/tasks/{task_id}/comments", json={"body": "hi"}, headers=account.headers).status_code == 201
    assert client.get(f"/tasks/{task_id}/comments", headers=account.headers).status_code == 200
    assert client.delete(f"/tasks/{created.json()['id']}", headers=account.headers).status_code == 204


# ---- role rules for membership ------------------------------------------------------


def add(client, team, actor, target, role="MEMBER"):
    return client.post(
        f"/workspaces/{team.workspace_id}/members",
        json={"user_id": target.id, "role": role},
        headers=actor.headers,
    )


def remove(client, team, actor, target):
    return client.delete(f"/workspaces/{team.workspace_id}/members/{target.id}", headers=actor.headers)


def roles(client, team, as_=None) -> dict[str, str]:
    viewer = as_ or team.owner
    detail = client.get(f"/workspaces/{team.workspace_id}", headers=viewer.headers).json()
    return {m["email"]: m["role"] for m in detail["members"]}


def test_member_cannot_add_members(client, team, make_account):
    newcomer = make_account("newcomer")
    response = add(client, team, team.member, newcomer)
    assert response.status_code == 403
    assert newcomer.email not in roles(client, team)


def test_member_cannot_remove_members(client, team):
    response = remove(client, team, team.member, team.admin)
    assert response.status_code == 403
    assert team.admin.email in roles(client, team)


def test_admin_can_add_and_remove_plain_members(client, team, make_account):
    newcomer = make_account("newcomer")
    assert add(client, team, team.admin, newcomer).status_code == 201
    assert remove(client, team, team.admin, newcomer).status_code == 204
    assert remove(client, team, team.admin, team.member).status_code == 204
    assert set(roles(client, team)) == {team.owner.email, team.admin.email}


@pytest.mark.parametrize("role", ["ADMIN", "OWNER"])
def test_admin_cannot_grant_admin_or_owner(client, team, make_account, role):
    newcomer = make_account("newcomer")
    response = add(client, team, team.admin, newcomer, role=role)
    assert response.status_code == 403
    assert response.json()["detail"] == f"Only an owner can grant the {role} role."
    assert newcomer.email not in roles(client, team)


@pytest.mark.parametrize("role", ["ADMIN", "OWNER"])
def test_owner_can_grant_admin_and_owner(client, team, make_account, role):
    newcomer = make_account("newcomer")
    assert add(client, team, team.owner, newcomer, role=role).status_code == 201
    assert roles(client, team)[newcomer.email] == role


def test_admin_cannot_remove_an_owner(client, team, make_account):
    # Even with a second owner around, so "last owner" is not what stops it.
    second_owner = make_account("secondowner")
    add(client, team, team.owner, second_owner, role="OWNER")

    response = remove(client, team, team.admin, second_owner)

    assert response.status_code == 403
    assert response.json()["detail"] == "Only an owner can remove another owner."
    assert roles(client, team)[second_owner.email] == "OWNER"


def test_last_owner_cannot_be_removed(client, team):
    response = remove(client, team, team.owner, team.owner)
    assert response.status_code == 409
    assert roles(client, team)[team.owner.email] == "OWNER"


def test_last_owner_cannot_leave(client, team):
    response = client.delete(f"/workspaces/{team.workspace_id}/members/me", headers=team.owner.headers)
    assert response.status_code == 409
    assert roles(client, team)[team.owner.email] == "OWNER"


def test_an_owner_can_be_removed_once_another_exists(client, team, make_account):
    second_owner = make_account("secondowner")
    add(client, team, team.owner, second_owner, role="OWNER")

    assert remove(client, team, second_owner, team.owner).status_code == 204
    remaining = roles(client, team, as_=second_owner)
    assert remaining[second_owner.email] == "OWNER"
    assert team.owner.email not in remaining


@pytest.mark.parametrize("role", ["admin", "member"])
def test_any_member_can_leave(client, team, role):
    account = getattr(team, role)
    assert client.delete(f"/workspaces/{team.workspace_id}/members/me", headers=account.headers).status_code == 204
    assert account.email not in roles(client, team)


@pytest.mark.parametrize("how", ["removed", "left"])
def test_former_member_loses_access_with_404(client, team, team_task, how):
    if how == "removed":
        remove(client, team, team.owner, team.member)
    else:
        client.delete(f"/workspaces/{team.workspace_id}/members/me", headers=team.member.headers)

    for method, path, body in SCOPED_ENDPOINTS:
        response = client.request(method, _fill(path, team, team_task), json=body, headers=team.member.headers)
        assert response.status_code == 404, (method, path, response.text)
