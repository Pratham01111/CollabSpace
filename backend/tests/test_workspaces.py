"""Workspaces and membership: the behaviour, given the caller is allowed.

Who is allowed is covered in test_authorization.py.
"""

import pytest


def test_create_workspace_makes_the_creator_owner(client, make_account):
    alice = make_account("alice")

    response = client.post("/workspaces", json={"name": "  Launch  "}, headers=alice.headers)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Launch"  # trimmed
    assert body["my_role"] == "OWNER"

    detail = client.get(f"/workspaces/{body['id']}", headers=alice.headers).json()
    assert [(m["email"], m["role"]) for m in detail["members"]] == [(alice.email, "OWNER")]


@pytest.mark.parametrize("body", [{}, {"name": ""}, {"name": "   "}, {"name": "x" * 121}])
def test_create_workspace_validates_name(client, make_account, body):
    alice = make_account("alice")
    assert client.post("/workspaces", json=body, headers=alice.headers).status_code == 422


def test_list_shows_only_my_workspaces_with_my_role(client, team, make_account):
    other = make_account("other")
    client.post("/workspaces", json={"name": "Not yours"}, headers=other.headers)

    for account, role in ((team.owner, "OWNER"), (team.admin, "ADMIN"), (team.member, "MEMBER")):
        listed = client.get("/workspaces", headers=account.headers).json()
        assert [(w["id"], w["my_role"]) for w in listed] == [(team.workspace_id, role)]


def test_detail_lists_members_with_roles(client, team):
    detail = client.get(f"/workspaces/{team.workspace_id}", headers=team.member.headers).json()

    assert detail["name"] == "Team"
    assert detail["my_role"] == "MEMBER"
    assert {m["email"]: m["role"] for m in detail["members"]} == {
        team.owner.email: "OWNER",
        team.admin.email: "ADMIN",
        team.member.email: "MEMBER",
    }


@pytest.mark.parametrize("by", ["email", "user_id"])
def test_add_member_by_email_or_id(client, team, make_account, by):
    newcomer = make_account("newcomer")
    body = {"email": newcomer.email} if by == "email" else {"user_id": newcomer.id}

    response = client.post(f"/workspaces/{team.workspace_id}/members", json=body, headers=team.owner.headers)

    assert response.status_code == 201
    assert response.json()["role"] == "MEMBER"  # the default
    assert client.get(f"/workspaces/{team.workspace_id}", headers=newcomer.headers).status_code == 200


def test_add_member_email_is_case_insensitive(client, team, make_account):
    newcomer = make_account("newcomer")
    response = client.post(
        f"/workspaces/{team.workspace_id}/members",
        json={"email": newcomer.email.upper()},
        headers=team.owner.headers,
    )
    assert response.status_code == 201


@pytest.mark.parametrize("body", [{}, {"email": "a@example.com", "user_id": 1}, {"email": "nope"}])
def test_add_member_needs_exactly_one_valid_identifier(client, team, body):
    response = client.post(f"/workspaces/{team.workspace_id}/members", json=body, headers=team.owner.headers)
    assert response.status_code == 422


@pytest.mark.parametrize("body", [{"email": "ghost@example.com"}, {"user_id": 999_999}])
def test_add_unknown_user_is_404(client, team, body):
    response = client.post(f"/workspaces/{team.workspace_id}/members", json=body, headers=team.owner.headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "No such user."


def test_add_existing_member_is_409(client, team):
    response = client.post(
        f"/workspaces/{team.workspace_id}/members", json={"user_id": team.member.id}, headers=team.owner.headers
    )
    assert response.status_code == 409


def test_remove_non_member_is_404(client, team):
    response = client.delete(f"/workspaces/{team.workspace_id}/members/{team.outsider.id}", headers=team.owner.headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "That user is not a member of this workspace."


def test_members_me_is_not_mistaken_for_a_user_id(client, team):
    """/members/me is its own route, registered ahead of /members/{user_id}."""
    response = client.delete(f"/workspaces/{team.workspace_id}/members/me", headers=team.member.headers)
    assert response.status_code == 204


def test_workspace_survives_its_members_leaving_and_keeps_its_tasks(client, team, team_task):
    client.delete(f"/workspaces/{team.workspace_id}/members/me", headers=team.admin.headers)
    client.delete(f"/workspaces/{team.workspace_id}/members/me", headers=team.member.headers)

    tasks = client.get(f"/workspaces/{team.workspace_id}/tasks", headers=team.owner.headers).json()
    assert [t["id"] for t in tasks] == [team_task["id"]]
